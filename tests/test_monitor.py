from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import monitor


def test_check_all_returns_three_channel_statuses(monkeypatch):
    cur = MagicMock()
    cur.fetchone.return_value = (None,)  # "no messages ever ingested" for outlook
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))
    monkeypatch.setattr(monitor, "_check_linkedin_liveness", lambda: monitor.ChannelStatus("linkedin", True, "ok"))

    statuses = monitor.check_all(cur)

    assert [s.channel for s in statuses] == ["outlook", "linkedin", "whatsapp"]
    assert statuses[0].healthy is False  # no messages ever ingested
    assert statuses[1].healthy is True
    assert statuses[2].healthy is True


def test_check_linkedin_liveness_missing_status_file_is_unhealthy(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "LINKEDIN_SYNC_STATUS_PATH", tmp_path / "missing.json")

    status = monitor._check_linkedin_liveness()

    assert status.healthy is False
    assert "never run" in status.detail


def test_check_linkedin_liveness_recent_run_with_no_new_messages_is_healthy(monkeypatch, tmp_path):
    # the exact real-world case this whole mechanism exists for: a
    # successful run that found nothing new must not read as unhealthy
    status_path = tmp_path / ".sync_status.json"
    status_path.write_text(json.dumps({
        "state": "ok",
        "detail": "synced 0 messages",
        "at": datetime.now(UTC).isoformat(),
    }))
    monkeypatch.setattr(monitor, "LINKEDIN_SYNC_STATUS_PATH", status_path)

    status = monitor._check_linkedin_liveness()

    assert status.healthy is True


def test_check_linkedin_liveness_capped_is_healthy(monkeypatch, tmp_path):
    status_path = tmp_path / ".sync_status.json"
    status_path.write_text(json.dumps({
        "state": "capped",
        "detail": "daily session limit reached — synced 2 before stopping",
        "at": datetime.now(UTC).isoformat(),
    }))
    monkeypatch.setattr(monitor, "LINKEDIN_SYNC_STATUS_PATH", status_path)

    status = monitor._check_linkedin_liveness()

    assert status.healthy is True


def test_check_linkedin_liveness_real_error_is_unhealthy(monkeypatch, tmp_path):
    status_path = tmp_path / ".sync_status.json"
    status_path.write_text(json.dumps({
        "state": "error",
        "detail": "sync failed: no saved session",
        "at": datetime.now(UTC).isoformat(),
    }))
    monkeypatch.setattr(monitor, "LINKEDIN_SYNC_STATUS_PATH", status_path)

    status = monitor._check_linkedin_liveness()

    assert status.healthy is False
    assert "sync failed" in status.detail


def test_check_linkedin_liveness_stale_successful_run_is_unhealthy(monkeypatch, tmp_path):
    # the mechanism ran fine at some point, but that was too long ago —
    # this is the "scheduler itself stopped firing" case, distinct from
    # "ran recently and found nothing new"
    status_path = tmp_path / ".sync_status.json"
    old = datetime.now(UTC) - timedelta(hours=30)
    status_path.write_text(json.dumps({
        "state": "ok",
        "detail": "synced 0 messages",
        "at": old.isoformat(),
    }))
    monkeypatch.setattr(monitor, "LINKEDIN_SYNC_STATUS_PATH", status_path)

    status = monitor._check_linkedin_liveness()

    assert status.healthy is False
    assert "threshold" in status.detail
