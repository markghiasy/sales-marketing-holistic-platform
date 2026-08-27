"""Pipeline health monitor (build plan §3, "Elsewhere" row — pipe-health
monitoring). Supersedes pipe_health.py's single "is anything reachable"
check with a per-channel staleness check and an actual alert, meant to run
on a schedule rather than by hand.

Two different kinds of signal, deliberately not conflated:

- Outlook / LinkedIn run as one-shot sync scripts, not long-lived
  processes — for these, "healthy" can only mean "the last sync ran
  recently and it wrote something," approximated here by
  max(message.ingested_at) per channel. This is a real limitation, not
  a placeholder: as of this script, nothing schedules those syncs to run
  automatically yet, so in practice this will report STALE once the
  threshold passes, correctly, because nothing scheduled a new run — see
  "Known gap" below.
- WhatsApp is a long-running connector (ingest.js). Message staleness
  alone can't tell "the socket died" apart from "nobody happened to
  message for a while" — a quiet chat looks identical to a dead
  connection if volume is all you check. ingest.js now writes its own
  liveness heartbeat to .heartbeat.txt every 60s (and immediately on
  connect); this checks that file's mtime instead of message volume.

Run: python scripts/monitor.py
Exit code 0 if every channel is healthy, 1 otherwise — so this composes
with any scheduler (cron, Windows Task Scheduler, a CI job) without
needing anything smarter than "did it exit non-zero."
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Windows' default console codepage isn't UTF-8, so the em-dashes used
# throughout this file's messages (and Windows is exactly where this
# monitor is expected to run first, per the local-dev setup) came out as
# mojibake without this — found by actually running the script, not by
# inspection.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

WHATSAPP_HEARTBEAT_PATH = (
    Path(__file__).parent.parent / "adapters" / "whatsapp" / "node" / ".heartbeat.txt"
)
ALERT_STATE_PATH = Path(__file__).parent / ".monitor_alert_state.json"

# Staleness thresholds per channel, in hours — overridable via env so
# these can tighten once real sync scheduling exists without a code
# change. Current defaults are deliberately generous (matched to how
# infrequently these currently run by hand) rather than a tuned SLA —
# tightening these is part of "Known gap" below, not done yet.
_DEFAULT_THRESHOLDS_HOURS = {
    "outlook": 24.0,
    "linkedin": 48.0,
}
_WHATSAPP_HEARTBEAT_THRESHOLD_MINUTES = 5.0  # ingest.js heartbeats every 60s
# don't re-send the same alert every run — only once per this many hours
# per channel, so a scheduled run every few minutes doesn't spam
_ALERT_COOLDOWN_HOURS = 6.0


@dataclass
class ChannelStatus:
    channel: str
    healthy: bool
    detail: str


def _threshold_hours(channel: str) -> float:
    env_key = f"MONITOR_{channel.upper()}_STALE_HOURS"
    return float(os.environ.get(env_key, _DEFAULT_THRESHOLDS_HOURS[channel]))


def _check_message_staleness(cur, channel: str) -> ChannelStatus:
    cur.execute("select max(ingested_at) from message where channel = %s", (channel,))
    (last_ingest,) = cur.fetchone()
    if last_ingest is None:
        return ChannelStatus(channel, False, "no messages ever ingested")

    age_hours = (datetime.now(UTC) - last_ingest).total_seconds() / 3600
    threshold = _threshold_hours(channel)
    if age_hours > threshold:
        return ChannelStatus(
            channel, False,
            f"last ingest {age_hours:.1f}h ago, threshold is {threshold:.0f}h "
            f"(last: {last_ingest.isoformat()})",
        )
    return ChannelStatus(channel, True, f"last ingest {age_hours:.1f}h ago")


def _check_whatsapp_liveness() -> ChannelStatus:
    if not WHATSAPP_HEARTBEAT_PATH.exists():
        return ChannelStatus(
            "whatsapp", False,
            f"no heartbeat file at {WHATSAPP_HEARTBEAT_PATH} — ingest.js has "
            "never run, or ran before this heartbeat feature existed",
        )
    age_minutes = (time.time() - WHATSAPP_HEARTBEAT_PATH.stat().st_mtime) / 60
    if age_minutes > _WHATSAPP_HEARTBEAT_THRESHOLD_MINUTES:
        return ChannelStatus(
            "whatsapp", False,
            f"connector heartbeat is {age_minutes:.1f}m old, threshold is "
            f"{_WHATSAPP_HEARTBEAT_THRESHOLD_MINUTES:.0f}m — ingest.js looks "
            "dead, not just quiet",
        )
    return ChannelStatus("whatsapp", True, f"connector heartbeat {age_minutes:.1f}m old")


def _load_alert_state() -> dict:
    if ALERT_STATE_PATH.exists():
        return json.loads(ALERT_STATE_PATH.read_text())
    return {}


def _save_alert_state(state: dict) -> None:
    ALERT_STATE_PATH.write_text(json.dumps(state))


def _send_alert(message: str) -> None:
    """Console output always happens — that's the floor. A Slack webhook
    is layered on top if MONITOR_ALERT_WEBHOOK_URL is set; nothing here
    depends on Mark having picked a destination yet, since he hasn't."""
    print(f"ALERT: {message}", file=sys.stderr)
    webhook_url = os.environ.get("MONITOR_ALERT_WEBHOOK_URL")
    if not webhook_url:
        return
    payload = json.dumps({"text": f"[pipe-health] {message}"}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # noqa: BLE001 — alerting must never itself crash the monitor
        print(f"ALERT DELIVERY FAILED (webhook): {e}", file=sys.stderr)


def run() -> int:
    load_dotenv()

    try:
        conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    except Exception as e:  # noqa: BLE001 — report, don't crash the caller
        _send_alert(f"cannot reach store at all: {e}")
        return 1

    statuses: list[ChannelStatus] = []
    with conn, conn.cursor() as cur:
        statuses.append(_check_message_staleness(cur, "outlook"))
        statuses.append(_check_message_staleness(cur, "linkedin"))
    statuses.append(_check_whatsapp_liveness())

    alert_state = _load_alert_state()
    now = time.time()
    any_unhealthy = False
    for status in statuses:
        if status.healthy:
            print(f"OK   {status.channel}: {status.detail}")
            alert_state.pop(status.channel, None)  # recovered — reset cooldown
            continue

        any_unhealthy = True
        print(f"FAIL {status.channel}: {status.detail}")
        last_alerted = alert_state.get(status.channel, 0)
        if now - last_alerted > _ALERT_COOLDOWN_HOURS * 3600:
            _send_alert(f"{status.channel} unhealthy — {status.detail}")
            alert_state[status.channel] = now

    _save_alert_state(alert_state)
    return 1 if any_unhealthy else 0


if __name__ == "__main__":
    sys.exit(run())
