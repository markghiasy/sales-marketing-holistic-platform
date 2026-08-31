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
