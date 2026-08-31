# tests/test_onboarding_app.py
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "onboarding"))

import app as onboarding_app
import monitor


@pytest.fixture(autouse=True)
def _reset_outlook_state():
    # _outlook_state is a module-level global shared by every test in this
    # file (the Flask app doesn't scope it per-instance), so a background
    # worker thread left over from one test's fake device-code flow can
    # otherwise mutate state a later test just reset — reset it before
    # each test to keep them independent.
    with onboarding_app._outlook_lock:
        onboarding_app._outlook_state.clear()
        onboarding_app._outlook_state["phase"] = "not_connected"
    yield


def test_status_route_returns_all_three_channels(monkeypatch):
    fake_cursor = MagicMock(fetchone=lambda: (None,))
    fake_cursor.connection = MagicMock()
    monkeypatch.setattr(onboarding_app, "_get_status_cursor", lambda: fake_cursor)
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"outlook", "linkedin", "whatsapp"}
    assert body["whatsapp"] == {"healthy": True, "detail": "ok"}


def test_status_route_degrades_when_db_unreachable(monkeypatch):
    import psycopg

    def _raise():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(onboarding_app, "_get_status_cursor", _raise)
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"outlook", "linkedin", "whatsapp"}
    assert body["outlook"]["healthy"] is False
    assert "connection refused" in body["outlook"]["detail"]
    assert body["linkedin"]["healthy"] is False
    assert "connection refused" in body["linkedin"]["detail"]
    assert body["whatsapp"] == {"healthy": True, "detail": "ok"}


def test_outlook_connect_then_status_shows_pending_code(monkeypatch):
    def fake_get_access_token(on_device_code=None):
        on_device_code({
            "message": "go to https://microsoft.com/devicelogin and enter ABC-123",
            "user_code": "ABC-123",
            "verification_uri": "https://microsoft.com/devicelogin",
        })
        # simulate the flow never completing within this test — the real
        # call blocks in its own background thread, so returning here
        # would normally happen after a real login; the test only checks
        # the pending state that /outlook/status reports meanwhile
        import time as _time
        _time.sleep(0.05)
        return "tok"

    monkeypatch.setattr(onboarding_app.outlook_client, "get_access_token", fake_get_access_token)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post("/outlook/connect")
    assert resp.status_code == 200

    import time as _time

    deadline = _time.monotonic() + 2.0
    body = None
    while _time.monotonic() < deadline:
        status_resp = client.get("/outlook/status")
        body = status_resp.get_json()
        if body["state"] != "starting":
            break
        _time.sleep(0.01)

    assert body["state"] == "pending"
    assert body["code"] == "ABC-123"
    assert body["url"] == "https://microsoft.com/devicelogin"

    # drain the background worker (it finishes ~0.05s after on_device_code)
    # so it can't land its "connected" update mid-flight during a later
    # test, which otherwise shares this same module-level _outlook_state
    deadline = _time.monotonic() + 2.0
    while _time.monotonic() < deadline:
        if client.get("/outlook/status").get_json()["state"] != "pending":
            break
        _time.sleep(0.01)


def test_outlook_connect_twice_returns_already_in_progress(monkeypatch):
    call_count = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    def fake_get_access_token(on_device_code=None):
        call_count["n"] += 1
        started.set()
        release.wait(timeout=2)
        return "tok"

    monkeypatch.setattr(onboarding_app.outlook_client, "get_access_token", fake_get_access_token)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp1 = client.post("/outlook/connect")
    assert resp1.status_code == 200
    assert resp1.get_json() == {"status": "started"}

    assert started.wait(timeout=2)

    resp2 = client.post("/outlook/connect")
    assert resp2.status_code == 200
    assert resp2.get_json() == {"status": "already_in_progress"}

    release.set()

    assert call_count["n"] == 1

    # drain the background worker (it finishes shortly after release.set())
    # so it can't land its "connected" update mid-flight during a later
    # test, which otherwise shares this same module-level _outlook_state
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if client.get("/outlook/status").get_json()["state"] not in ("starting", "pending"):
            break
        time.sleep(0.01)


def test_outlook_connect_handles_generic_exception(monkeypatch):
    def fake_get_access_token(on_device_code=None):
        # a plain Exception, deliberately not RuntimeError, to prove the
        # worker's except clause isn't narrowly scoped to RuntimeError
        raise Exception("boom: something unexpected happened")  # noqa: TRY002

    monkeypatch.setattr(onboarding_app.outlook_client, "get_access_token", fake_get_access_token)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post("/outlook/connect")
    assert resp.status_code == 200

    deadline = time.monotonic() + 2.0
    body = None
    while time.monotonic() < deadline:
        status_resp = client.get("/outlook/status")
        body = status_resp.get_json()
        if body["state"] != "starting":
            break
        time.sleep(0.01)

    assert body["state"] == "error"
    assert body["error"]


def test_whatsapp_status_reads_status_json(monkeypatch, tmp_path):
    status_path = tmp_path / ".status.json"
    status_path.write_text(json.dumps({"state": "connected", "detail": "connected as 123", "at": "now"}))
    monkeypatch.setattr(monitor, "WHATSAPP_STATUS_PATH", status_path)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/whatsapp/status")
    assert resp.get_json() == {"state": "connected", "detail": "connected as 123", "at": "now"}


def test_whatsapp_status_not_connected_when_no_status_file(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "WHATSAPP_STATUS_PATH", tmp_path / "missing.json")

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/whatsapp/status")
    assert resp.get_json() == {"state": "not_connected"}


def test_whatsapp_status_handles_malformed_json(monkeypatch, tmp_path):
    # simulates ingest.js's writeStatus() (a non-atomic fs.writeFileSync)
    # being read mid-write — the file exists but isn't valid JSON yet.
    status_path = tmp_path / ".status.json"
    status_path.write_text('{"state": "connected", "detail": "conn')  # truncated
    monkeypatch.setattr(monitor, "WHATSAPP_STATUS_PATH", status_path)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/whatsapp/status")

    # must not 500, and must fall back to the exact same shape as the
    # "no status file at all" case for consistency
    assert resp.status_code == 200
    assert resp.get_json() == {"state": "not_connected"}


def test_whatsapp_connect_rapid_fire_only_spawns_once(monkeypatch, tmp_path):
    # simulates two /whatsapp/connect requests arriving before ingest.js
    # has had a chance to write its own .pid file (a real, hundreds-of-ms
    # window in production) — neither call can see a live pid yet, so
    # without the in-progress guard both would spawn a duplicate process.
    onboarding_app._whatsapp_spawn_started_at = None
    monkeypatch.setattr(monitor, "WHATSAPP_PID_PATH", tmp_path / "missing.pid")

    popen_mock = MagicMock()
    monkeypatch.setattr(onboarding_app.subprocess, "Popen", popen_mock)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp1 = client.post("/whatsapp/connect")
    resp2 = client.post("/whatsapp/connect")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert popen_mock.call_count == 1
    assert resp2.get_json() == {"status": "already_running"}

    onboarding_app._whatsapp_spawn_started_at = None


def test_whatsapp_connect_popen_failure_clears_flag_and_returns_clean_error(monkeypatch, tmp_path):
    # simulates Popen() itself raising synchronously (e.g. "node" isn't on
    # PATH, or the whatsapp cwd doesn't exist) — this used to leave the
    # in-progress flag stuck True forever and 500 the request instead of
    # reporting a clean error.
    onboarding_app._whatsapp_spawn_started_at = None
    monkeypatch.setattr(monitor, "WHATSAPP_PID_PATH", tmp_path / "missing.pid")

    failing_popen = MagicMock(side_effect=FileNotFoundError("[WinError 2] node not found"))
    monkeypatch.setattr(onboarding_app.subprocess, "Popen", failing_popen)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post("/whatsapp/connect")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "error"
    assert "node not found" in body["detail"]

    # the flag must be cleared, not just the response — prove it with a
    # subsequent call that has a working Popen and should actually spawn
    working_popen = MagicMock()
    monkeypatch.setattr(onboarding_app.subprocess, "Popen", working_popen)

    resp2 = client.post("/whatsapp/connect")

    assert resp2.status_code == 200
    assert resp2.get_json() == {"status": "started"}
    assert working_popen.call_count == 1

    onboarding_app._whatsapp_spawn_started_at = None


def test_whatsapp_connect_stale_flag_self_heals_after_grace_period(monkeypatch, tmp_path):
    # simulates finding #1: ingest.js exits (e.g. a require() failure)
    # before it ever gets far enough to write .pid, so there's no live pid
    # to observe and no Python-side exception to catch — nothing else
    # would ever clear the flag. Set it as if a spawn happened long enough
    # ago that ingest.js should have written .pid by now if it were going
    # to; /whatsapp/connect should treat it as stale and retry instead of
    # reporting "already_running" forever.
    onboarding_app._whatsapp_spawn_started_at = (
        time.monotonic() - onboarding_app._WHATSAPP_SPAWN_GRACE_SECONDS - 1.0
    )
    monkeypatch.setattr(monitor, "WHATSAPP_PID_PATH", tmp_path / "missing.pid")

    popen_mock = MagicMock()
    monkeypatch.setattr(onboarding_app.subprocess, "Popen", popen_mock)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post("/whatsapp/connect")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started"}
    assert popen_mock.call_count == 1

    onboarding_app._whatsapp_spawn_started_at = None
