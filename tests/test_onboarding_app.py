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
def _reset_outlook_state(monkeypatch, tmp_path):
    # _outlook_state is a module-level global shared by every test in this
    # file (the Flask app doesn't scope it per-instance), so a background
    # worker thread left over from one test's fake device-code flow can
    # otherwise mutate state a later test just reset — reset it before
    # each test to keep them independent.
    with onboarding_app._outlook_lock:
        onboarding_app._outlook_state.clear()
        onboarding_app._outlook_state["phase"] = "not_connected"

    # /outlook/connect and /outlook/status both check the on-disk token
    # cache (has_valid_cached_token) before falling back to in-memory
    # state — found the hard way: this whole file's suite passed cleanly
    # against a fresh checkout, then failed against the real repo, where
    # .token_cache.bin genuinely held a valid token from actual Outlook
    # use. Point every test at an empty tmp path by default so "not
    # connected yet" tests don't silently depend on whatever real cache
    # happens to exist on the machine running the suite; tests that
    # specifically exercise the cached-token path set their own valid
    # cache file and can override this via their own monkeypatch call.
    monkeypatch.setattr(onboarding_app.outlook_client, "TOKEN_CACHE_PATH", tmp_path / ".token_cache.bin")
    yield


def test_status_route_returns_all_three_channels(monkeypatch):
    monkeypatch.setattr(monitor, "_check_outlook_liveness", lambda: monitor.ChannelStatus("outlook", True, "ok"))
    monkeypatch.setattr(monitor, "_check_linkedin_liveness", lambda: monitor.ChannelStatus("linkedin", True, "ok"))
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"outlook", "linkedin", "whatsapp"}
    assert body["whatsapp"] == {"healthy": True, "detail": "ok"}
    assert body["linkedin"] == {"healthy": True, "detail": "ok"}
    assert body["outlook"] == {"healthy": True, "detail": "ok"}


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


def test_outlook_status_reports_connected_from_disk_cache_after_restart(monkeypatch, tmp_path):
    # simulates the process restarting: _outlook_state is back to its
    # in-memory default (not_connected, reset by the autouse fixture), but
    # a valid, unexpired token is already sitting in the on-disk cache from
    # a previous run — /outlook/status must derive "connected" from that
    # instead of reporting not_connected just because nothing has happened
    # in *this* process yet.
    cache_path = tmp_path / ".token_cache.bin"
    cache_path.write_text(json.dumps({
        "access_token": "cached-tok",
        "scopes": onboarding_app.outlook_client.SCOPES,
        "expires_at": time.time() + 3600,
    }))
    monkeypatch.setattr(onboarding_app.outlook_client, "TOKEN_CACHE_PATH", cache_path)
    monkeypatch.setenv("OUTLOOK_MAILBOX", "eva@example.com")

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/outlook/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["state"] == "connected"
    assert body["mailbox"] == "eva@example.com"


def test_outlook_connect_with_valid_cached_token_returns_already_connected_without_starting_flow(monkeypatch, tmp_path):
    # same "process just restarted, valid token already on disk" scenario
    # as above, but hitting /outlook/connect: it must short-circuit to
    # already_connected and must NOT kick off a brand-new device-code
    # flow — proven here by asserting get_access_token() (the thing that
    # would start a real device-code login) is never called.
    cache_path = tmp_path / ".token_cache.bin"
    cache_path.write_text(json.dumps({
        "access_token": "cached-tok",
        "scopes": onboarding_app.outlook_client.SCOPES,
        "expires_at": time.time() + 3600,
    }))
    monkeypatch.setattr(onboarding_app.outlook_client, "TOKEN_CACHE_PATH", cache_path)

    get_access_token_mock = MagicMock(side_effect=AssertionError("should not be called"))
    monkeypatch.setattr(onboarding_app.outlook_client, "get_access_token", get_access_token_mock)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post("/outlook/connect")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "already_connected"}

    # give any (incorrectly) spawned worker thread a moment to run, so a
    # regression that does start the flow would actually invoke the mock
    # before this test asserts on it
    time.sleep(0.05)
    get_access_token_mock.assert_not_called()


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


def test_linkedin_download_helper_embeds_a_fresh_token(monkeypatch):
    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/linkedin/download-helper")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "{{TOKEN}}" not in body
    assert "{{BASE_URL}}" not in body
    assert "def main()" in body


def test_linkedin_upload_session_rejects_unknown_token(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding_app.linkedin_login, "STORAGE_STATE_PATH", tmp_path / ".storage_state.json")
    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post(
        "/linkedin/upload-session",
        json={"cookies": []},
        headers={"X-Onboarding-Token": "not-a-real-token"},
    )
    assert resp.status_code == 403


def test_linkedin_upload_session_accepts_valid_token_then_rejects_reuse(tmp_path, monkeypatch):
    storage_path = tmp_path / ".storage_state.json"
    monkeypatch.setattr(onboarding_app.linkedin_login, "STORAGE_STATE_PATH", storage_path)
    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    download_resp = client.get("/linkedin/download-helper")
    body = download_resp.get_data(as_text=True)
    token = body.split('TOKEN = "')[1].split('"')[0]

    upload_resp = client.post(
        "/linkedin/upload-session",
        json={"cookies": ["fake"]},
        headers={"X-Onboarding-Token": token},
    )
    assert upload_resp.status_code == 200
    assert json.loads(storage_path.read_text()) == {"cookies": ["fake"]}

    reuse_resp = client.post(
        "/linkedin/upload-session",
        json={"cookies": ["fake"]},
        headers={"X-Onboarding-Token": token},
    )
    assert reuse_resp.status_code == 403


def test_linkedin_upload_session_concurrent_requests_only_one_accepted(tmp_path, monkeypatch):
    # proves _linkedin_tokens_lock actually serializes the check-then-mark
    # sequence in linkedin_upload_session(): fire many genuinely concurrent
    # requests with the same valid, single-use token (synchronized with a
    # Barrier so they all reach the endpoint at once) and assert exactly one
    # is accepted. Without the lock around the "token not yet used?" check
    # and the "mark it used" write, multiple threads can each observe the
    # token as unused before any of them marks it, so more than one would
    # be accepted here.
    #
    # Barrier(n_threads) only synchronizes thread *start* though — it does
    # nothing to guarantee any two threads are executing inside the actual
    # check-then-mark window (a couple of bytecodes) at the same instant,
    # and that window is far too narrow for the GIL's ~5ms preemption timer
    # to reliably land inside it. Left alone, this test passes even against
    # unlocked code essentially 100% of the time — it wouldn't catch a
    # regression. So we force the race deterministically: monkeypatch the
    # route's _token_check_delay_hook() (a no-op in production, called
    # between the check and the mark, inside the lock) to sleep briefly.
    # With the lock present, that sleep happens one thread at a time and
    # every other thread blocks on the lock during it. Without the lock,
    # every thread's check-then-sleep-then-mark window overlaps and
    # multiple threads observe "unused" before any of them marks it,
    # so this test fails against unlocked code and passes against locked
    # code — see the Fix Report in .superpowers/sdd/task-7-report.md for
    # the before/after evidence.
    monkeypatch.setattr(onboarding_app, "_token_check_delay_hook", lambda: time.sleep(0.05))
    storage_path = tmp_path / ".storage_state.json"
    monkeypatch.setattr(onboarding_app.linkedin_login, "STORAGE_STATE_PATH", storage_path)
    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    download_resp = client.get("/linkedin/download-helper")
    body = download_resp.get_data(as_text=True)
    token = body.split('TOKEN = "')[1].split('"')[0]

    n_threads = 25
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads

    def worker(i):
        barrier.wait(timeout=5)
        resp = client.post(
            "/linkedin/upload-session",
            json={"cookies": ["fake"]},
            headers={"X-Onboarding-Token": token},
        )
        results[i] = resp.status_code

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results.count(200) == 1
    assert results.count(403) == n_threads - 1


import datetime as _dt
import uuid as _uuid

import psycopg as _psycopg

# same local Postgres URL tests/conftest.py's db_conn fixture uses,
# deliberately hardcoded there (not read from .env) because .env's
# DATABASE_URL points at the real hosted Supabase project — this file's
# resolution routes share one persistent connection via _db_cursor()
# (scripts/onboarding/app.py), opened against os.environ["DATABASE_URL"]
# the first time any route in this class is called and reused after
# that. Without redirecting that env var for the duration of these
# tests, every route call below would silently connect to and mutate
# the real production database instead of the local db_conn fixture's
# Postgres, while the test's own seeded rows (via db_conn) would sit in
# a completely separate database the route never sees. Caught by hand-
# tracing this exact mismatch before dispatch — not a hypothetical.
_RESOLUTION_TEST_DATABASE_URL = "postgresql://comms:comms@localhost:5432/comms"


class TestResolutionReviewQueue:
    @pytest.fixture(autouse=True)
    def _routes_use_local_db(self, monkeypatch):
        # autouse + defined inside the class, so this only wraps tests in
        # THIS class — every other test in the file is unaffected.
        monkeypatch.setenv("DATABASE_URL", _RESOLUTION_TEST_DATABASE_URL)

    @pytest.fixture
    def _created_identity_ids(self, db_conn):
        # Every test in this class calls db_conn.commit() (needed so the
        # route's OWN, separate connection — held open across requests by
        # _db_cursor() — can see the rows this test just inserted; a
        # plain uncommitted transaction is invisible across connections).
        # That means, unlike every other test in this plan, these tests
        # cannot rely on db_conn's own rollback-on-teardown for isolation
        # — a committed row stays in the local test database forever.
        # Found the hard way: rule_linkedin_correlation's tests
        # (tests/test_resolution_linkedin_correlation.py) do an unscoped
        # `select ... from identity where channel in ('outlook',
        # 'whatsapp')` scan — exactly matching that rule's real production
        # behaviour — so a leftover "Eric Tham"/"Eric" identity pair
        # committed here and never cleaned up collides with that other
        # file's fixed test names the next time the whole suite runs.
        # Tests append the ids they create to this list; this fixture
        # deletes them (and any link_candidate/merge_log row referencing
        # them) after the test body runs, restoring real isolation
        # despite the commit.
        ids: list = []
        yield ids
        if ids:
            cur = db_conn.cursor()
            cur.execute(
                "delete from link_candidate where identity_a_id = any(%s) or identity_b_id = any(%s)",
                (ids, ids),
            )
            # merge_log.identity_a_id/identity_b_id FK identity — added by
            # the reversible-identity-merge change; without this, deleting
            # an identity that a confirmed merge in this test logged fails
            # with a ForeignKeyViolation instead of cleaning up.
            cur.execute(
                "delete from merge_log where identity_a_id = any(%s) or identity_b_id = any(%s)",
                (ids, ids),
            )
            cur.execute("delete from identity where id = any(%s)", (ids,))
            db_conn.commit()

    def test_get_resolution_candidates_json_lists_pending(self, db_conn, _created_identity_ids):
        # the /resolution page itself renders client-side (fetches
        # candidates.json via JS, see the template in Step 3) — assert on
        # the JSON endpoint directly rather than the initial HTML, which
        # never contains "test reason" verbatim
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle, display_name) values ('outlook', %s, 'Eric Tham') returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle, display_name) values ('whatsapp', %s, 'Eric') returning id", (b_handle,))
        b = cur.fetchone()[0]
        _created_identity_ids.extend([a, b])
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason) values (%s, %s, 0.5, 'test', 'pending', 'test reason')",
            (a, b),
        )
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.get("/resolution/candidates.json")

        assert resp.status_code == 200
        body = resp.get_json()
        assert any(item["reason"] == "test reason" for item in body)

        # real gap found 2026-09-09: a reviewer can't judge a merge from a
        # display_name alone (often blank/"(no name)") — the actual
        # identifier (email/phone) has to be there to make a real call
        item = next(item for item in body if item["reason"] == "test reason")
        assert item["handle_a"] == a_email
        assert item["handle_b"] == b_handle

    def test_confirm_candidate_applies_the_merge(self, db_conn, _created_identity_ids):
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle, display_name) values ('outlook', %s, 'Eric Tham') returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle, display_name) values ('whatsapp', %s, 'Eric') returning id", (b_handle,))
        b = cur.fetchone()[0]
        _created_identity_ids.extend([a, b])
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) values (%s, %s, 0.5, 'test', 'pending') returning id",
            (a, b),
        )
        candidate_id = cur.fetchone()[0]
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.post(f"/resolution/candidate/{candidate_id}/confirm")

        assert resp.status_code == 200
        cur.execute("select person_id from identity where id = %s", (a,))
        assert cur.fetchone()[0] is not None
        cur.execute("select status from link_candidate where id = %s", (candidate_id,))
        assert cur.fetchone()[0] == "confirmed"

    def test_confirming_twice_only_merges_and_logs_once(self, db_conn, _created_identity_ids):
        # Regression test for 2026-09-09: a double/triple/quintuple click
        # on a Confirm button that gives no visible feedback used to reach
        # the server as N separate requests, each reading status='pending'
        # before the first one's UPDATE committed, so each called
        # apply_merge and wrote its own merge_log row for what should be
        # one merge event. The route now claims the row with an atomic
        # UPDATE ... WHERE status = 'pending' before merging, so only the
        # first of any repeat requests actually merges.
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle) values ('outlook', %s) returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle) values ('whatsapp', %s) returning id", (b_handle,))
        b = cur.fetchone()[0]
        _created_identity_ids.extend([a, b])
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) values (%s, %s, 0.5, 'test', 'pending') returning id",
            (a, b),
        )
        candidate_id = cur.fetchone()[0]
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        first = client.post(f"/resolution/candidate/{candidate_id}/confirm")
        second = client.post(f"/resolution/candidate/{candidate_id}/confirm")

        assert first.status_code == 200 and first.get_json()["status"] == "confirmed"
        assert second.status_code == 200 and second.get_json()["status"] == "no_op"
        cur.execute("select count(*) from merge_log where identity_a_id = %s and identity_b_id = %s", (a, b))
        assert cur.fetchone()[0] == 1

    def test_reject_candidate_does_not_merge(self, db_conn, _created_identity_ids):
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle) values ('outlook', %s) returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle) values ('whatsapp', %s) returning id", (b_handle,))
        b = cur.fetchone()[0]
        _created_identity_ids.extend([a, b])
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) values (%s, %s, 0.5, 'test', 'pending') returning id",
            (a, b),
        )
        candidate_id = cur.fetchone()[0]
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.post(f"/resolution/candidate/{candidate_id}/reject")

        assert resp.status_code == 200
        cur.execute("select status from link_candidate where id = %s", (candidate_id,))
        assert cur.fetchone()[0] == "rejected"
        cur.execute("select person_id from identity where id = %s", (a,))
        assert cur.fetchone()[0] is None

    def test_confirm_is_a_no_op_on_a_non_pending_candidate(self, db_conn, _created_identity_ids):
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle) values ('outlook', %s) returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle) values ('whatsapp', %s) returning id", (b_handle,))
        b = cur.fetchone()[0]
        _created_identity_ids.extend([a, b])
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) values (%s, %s, 0.5, 'test', 'rejected') returning id",
            (a, b),
        )
        candidate_id = cur.fetchone()[0]
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.post(f"/resolution/candidate/{candidate_id}/confirm")

        assert resp.status_code == 200
        cur.execute("select status from link_candidate where id = %s", (candidate_id,))
        assert cur.fetchone()[0] == "rejected"  # unchanged, not flipped to confirmed


def _seed_inbox_conversation(db_conn, created_ids: dict) -> str:
    """Seeds one contact identity with a single inbound message, matching
    the shape adapters/inbox_query.py's list_conversations/get_detail
    queries expect (contact_stats/contact_last_message views, plus the
    identity/thread/message/message_participant tables directly for
    get_detail). Returns the contact identity's id, which is also its
    person_key (coalesce(person_id, id) — person_id is left null here).

    Commits (rather than relying on db_conn's rollback-on-teardown) because
    the Flask app's _db_cursor() holds its own, separate connection — an
    uncommitted insert on db_conn would be invisible to it. created_ids is
    filled in so the caller's cleanup fixture can delete everything this
    inserts afterward, same pattern TestResolutionReviewQueue's
    _created_identity_ids fixture uses for the same reason (a committed row
    doesn't get cleaned up by db_conn's rollback and would otherwise sit in
    the local test database forever).
    """
    cur = db_conn.cursor()
    cur.execute(
        "insert into identity (channel, handle, is_self) values (%s, %s, %s) returning id",
        ("outlook", f"me-{_uuid.uuid4().hex}@example.com", True),
    )
    self_id = str(cur.fetchone()[0])
    cur.execute(
        "insert into identity (channel, handle, is_self, display_name) values (%s, %s, %s, %s) returning id",
        ("outlook", f"c-{_uuid.uuid4().hex}@example.com", False, "Test Contact"),
    )
    contact_id = str(cur.fetchone()[0])
    cur.execute(
        "insert into thread (channel, external_id, last_read_at) values (%s, %s, %s) returning id",
        ("outlook", f"thread-{_uuid.uuid4().hex}", None),
    )
    thread_id = str(cur.fetchone()[0])
    now = _dt.datetime.now(_dt.UTC)
    cur.execute(
        """
        insert into message (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, raw)
        values (%s, %s, %s, %s, %s, %s, %s, %s) returning id
        """,
        (thread_id, "outlook", f"msg-{_uuid.uuid4().hex}", "inbound", now, contact_id, "hello", _psycopg.types.json.Json({})),
    )
    message_id = str(cur.fetchone()[0])
    cur.execute("insert into message_participant (message_id, identity_id, role) values (%s, %s, 'from')", (message_id, contact_id))
    cur.execute("insert into message_participant (message_id, identity_id, role) values (%s, %s, 'to')", (message_id, self_id))
    db_conn.commit()

    created_ids["identity_ids"] = [self_id, contact_id]
    created_ids["thread_id"] = thread_id
    created_ids["message_id"] = message_id
    return contact_id


class TestInboxRoutes:
    @pytest.fixture(autouse=True)
    def _routes_use_local_db(self, monkeypatch):
        # same rationale as TestResolutionReviewQueue's fixture of the same
        # name above: /inbox/*.json routes go through _db_cursor(), which
        # connects to os.environ["DATABASE_URL"] — point that at the local
        # docker-compose Postgres db_conn also targets, not the real
        # hosted Supabase instance .env's DATABASE_URL points at.
        monkeypatch.setenv("DATABASE_URL", _RESOLUTION_TEST_DATABASE_URL)

    @pytest.fixture
    def _created(self, db_conn):
        # mirrors TestResolutionReviewQueue's _created_identity_ids fixture:
        # _seed_inbox_conversation commits (see its own docstring), so
        # db_conn's rollback-on-teardown can't clean these rows up — do it
        # by hand here instead.
        created_ids: dict = {}
        yield created_ids
        if created_ids:
            cur = db_conn.cursor()
            cur.execute("delete from message_participant where message_id = %s", (created_ids["message_id"],))
            cur.execute("delete from message where id = %s", (created_ids["message_id"],))
            cur.execute("delete from thread where id = %s", (created_ids["thread_id"],))
            cur.execute("delete from identity where id = any(%s)", (created_ids["identity_ids"],))
            db_conn.commit()

    def test_conversations_json_lists_seeded_contact(self, db_conn, _created):
        contact_id = _seed_inbox_conversation(db_conn, _created)

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.get("/inbox/conversations.json")

        assert resp.status_code == 200
        rows = resp.get_json()
        assert any(r["person_key"] == contact_id for r in rows)

    def test_conversation_detail_json_returns_threads(self, db_conn, _created):
        contact_id = _seed_inbox_conversation(db_conn, _created)

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.get(f"/inbox/conversation/{contact_id}.json")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["name"] == "Test Contact"
        assert body["threads"][0]["messages"][0]["text"] == "hello"

    def test_conversation_detail_json_404s_for_unknown_person(self):
        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.get(f"/inbox/conversation/{_uuid.uuid4()}.json")
        assert resp.status_code == 404

    def test_mark_read_updates_thread(self, db_conn, _created):
        contact_id = _seed_inbox_conversation(db_conn, _created)

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.post(f"/inbox/conversation/{contact_id}/read")

        assert resp.status_code == 200
        cur = db_conn.cursor()
        cur.execute(
            """
            select last_read_at from thread t
            join message m on m.thread_id = t.id
            join message_participant mp on mp.message_id = m.id
            where mp.identity_id = %s
            """,
            (contact_id,),
        )
        assert cur.fetchone()[0] is not None
