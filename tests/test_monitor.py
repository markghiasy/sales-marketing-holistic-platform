from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import monitor


def test_check_all_returns_three_channel_statuses(monkeypatch):
    monkeypatch.setattr(monitor, "_check_outlook_liveness", lambda: monitor.ChannelStatus("outlook", True, "ok"))
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))
    monkeypatch.setattr(monitor, "_check_linkedin_liveness", lambda: monitor.ChannelStatus("linkedin", True, "ok"))

    statuses = monitor.check_all()

    assert [s.channel for s in statuses] == ["outlook", "linkedin", "whatsapp"]
    assert all(s.healthy for s in statuses)


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


def test_check_outlook_liveness_missing_status_file_is_unhealthy(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "OUTLOOK_SYNC_STATUS_PATH", tmp_path / "missing.json")

    status = monitor._check_outlook_liveness()

    assert status.healthy is False
    assert "never run" in status.detail


def test_check_outlook_liveness_recent_run_with_no_new_messages_is_healthy(monkeypatch, tmp_path):
    # the exact real-world case this whole mechanism exists for: a mailbox
    # that's had no new mail in over a day is not the same as a broken sync
    status_path = tmp_path / ".sync_status.json"
    status_path.write_text(json.dumps({
        "state": "ok",
        "detail": "synced 0 messages",
        "at": datetime.now(UTC).isoformat(),
    }))
    monkeypatch.setattr(monitor, "OUTLOOK_SYNC_STATUS_PATH", status_path)

    status = monitor._check_outlook_liveness()

    assert status.healthy is True


def test_check_outlook_liveness_real_error_is_unhealthy(monkeypatch, tmp_path):
    status_path = tmp_path / ".sync_status.json"
    status_path.write_text(json.dumps({
        "state": "error",
        "detail": "sync failed: token expired",
        "at": datetime.now(UTC).isoformat(),
    }))
    monkeypatch.setattr(monitor, "OUTLOOK_SYNC_STATUS_PATH", status_path)

    status = monitor._check_outlook_liveness()

    assert status.healthy is False
    assert "sync failed" in status.detail


def test_check_outlook_liveness_stale_successful_run_is_unhealthy(monkeypatch, tmp_path):
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
    monkeypatch.setattr(monitor, "OUTLOOK_SYNC_STATUS_PATH", status_path)

    status = monitor._check_outlook_liveness()

    assert status.healthy is False
    assert "threshold" in status.detail


# Regression tests for 2026-09-10: _pid_is_alive, _start_whatsapp_detached,
# and the ZOMBIE branch of _attempt_whatsapp_auto_heal used Windows-only
# tools/APIs (tasklist, taskkill, subprocess.DETACHED_PROCESS) unconditionally
# — the detach call raised AttributeError outright on POSIX, and the other
# two silently no-opped. Force the POSIX branch via sys.platform regardless
# of the host these tests actually run on, so the fix is verified either way.


def test_pid_is_alive_on_posix_uses_os_kill_signal_zero(monkeypatch):
    monkeypatch.setattr(monitor.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(monitor.os, "kill", lambda pid, sig: calls.append((pid, sig)))

    assert monitor._pid_is_alive(1234) is True
    assert calls == [(1234, 0)]


def test_pid_is_alive_on_posix_process_lookup_error_means_dead(monkeypatch):
    monkeypatch.setattr(monitor.sys, "platform", "linux")

    def fake_kill(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr(monitor.os, "kill", fake_kill)

    assert monitor._pid_is_alive(1234) is False


def test_pid_is_alive_on_posix_permission_error_means_alive(monkeypatch):
    # exists but owned by someone else — still alive, from monitor's
    # point of view
    monkeypatch.setattr(monitor.sys, "platform", "linux")

    def fake_kill(pid, sig):
        raise PermissionError()
    monkeypatch.setattr(monitor.os, "kill", fake_kill)

    assert monitor._pid_is_alive(1234) is True


def test_start_whatsapp_detached_on_posix_uses_start_new_session_not_creationflags(monkeypatch):
    monkeypatch.setattr(monitor.sys, "platform", "linux")
    calls = {}

    def fake_popen(*args, **kwargs):
        calls["kwargs"] = kwargs
    monkeypatch.setattr(monitor.subprocess, "Popen", fake_popen)

    monitor._start_whatsapp_detached()

    assert calls["kwargs"].get("start_new_session") is True
    assert "creationflags" not in calls["kwargs"]


def test_zombie_auto_heal_on_posix_uses_os_kill_sigkill(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor.sys, "platform", "linux")
    pid_path = tmp_path / ".pid"
    pid_path.write_text("4321")
    monkeypatch.setattr(monitor, "WHATSAPP_PID_PATH", pid_path)
    monkeypatch.setattr(monitor, "_start_whatsapp_detached", lambda: None)
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))
    monkeypatch.setattr(monitor.time, "sleep", lambda _seconds: None)

    calls = []
    monkeypatch.setattr(monitor.os, "kill", lambda pid, sig: calls.append((pid, sig)))

    monitor._attempt_whatsapp_auto_heal(monitor.ChannelStatus("whatsapp", False, "ZOMBIE — process 4321 is stale"))

    assert calls == [(4321, getattr(monitor.signal, "SIGKILL", 9))]
