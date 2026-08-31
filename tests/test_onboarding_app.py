# tests/test_onboarding_app.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "onboarding"))

import app as onboarding_app
import monitor


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
    _time.sleep(0.01)  # let the background thread reach on_device_code
    status_resp = client.get("/outlook/status")
    body = status_resp.get_json()
    assert body["state"] == "pending"
    assert body["code"] == "ABC-123"
    assert body["url"] == "https://microsoft.com/devicelogin"
