# tests/test_onboarding_app.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "onboarding"))

import app as onboarding_app  # noqa: E402
import monitor  # noqa: E402


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
