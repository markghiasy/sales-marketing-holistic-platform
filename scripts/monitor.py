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
import subprocess
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

_WHATSAPP_DIR = Path(__file__).parent.parent / "adapters" / "whatsapp" / "node"
WHATSAPP_HEARTBEAT_PATH = _WHATSAPP_DIR / ".heartbeat.txt"
WHATSAPP_STATUS_PATH = _WHATSAPP_DIR / ".status.json"
WHATSAPP_PID_PATH = _WHATSAPP_DIR / ".pid"
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


def _pid_is_alive(pid: int) -> bool:
    # os.kill(pid, 0) isn't a liveness check on Windows the way it is on
    # POSIX — shell out to tasklist and check whether it actually lists
    # the pid, rather than trust a signal call that doesn't mean the same
    # thing here.
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except Exception:  # noqa: BLE001 — can't determine, treat as unknown-not-alive
        return False
    return str(pid) in out


def _check_whatsapp_liveness() -> ChannelStatus:
    """Distinguishes the states that actually matter operationally, not
    just healthy/unhealthy — 2026-08-31, in direct response to "how do we
    even tell if it's a zombie or a live one, and what do we do about
    it": a stale heartbeat alone can mean four different things, each
    with a different fix, and conflating them into one generic "looks
    dead" message is exactly what left a zombie connector undiagnosed
    for days. Every unhealthy branch below names the actual next
    command, not just the symptom."""
    if not WHATSAPP_HEARTBEAT_PATH.exists():
        return ChannelStatus(
            "whatsapp", False,
            "never run yet, or ran before this monitoring existed — "
            "start it: `node adapters/whatsapp/node/ingest.js`",
        )

    status = {}
    if WHATSAPP_STATUS_PATH.exists():
        try:
            status = json.loads(WHATSAPP_STATUS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass  # treat as no status available — heartbeat age still decides
    state = status.get("state")

    if state == "logged_out":
        return ChannelStatus(
            "whatsapp", False,
            "session logged out by WhatsApp — delete "
            "adapters/whatsapp/node/.auth_state and run `node ingest.js` "
            "again, then scan the new qr.png",
        )
    if state == "qr_pending":
        return ChannelStatus(
            "whatsapp", False,
            "waiting on a QR scan to pair — open "
            "adapters/whatsapp/node/qr.png and scan it in WhatsApp",
        )
    if state == "crashed":
        return ChannelStatus(
            "whatsapp", False,
            f"connector crashed ({status.get('detail', 'no detail')}) — "
            "restart it: `node adapters/whatsapp/node/ingest.js`, then "
            "check .connection_log.txt if it happens again",
        )

    age_minutes = (time.time() - WHATSAPP_HEARTBEAT_PATH.stat().st_mtime) / 60
    if age_minutes <= _WHATSAPP_HEARTBEAT_THRESHOLD_MINUTES:
        return ChannelStatus("whatsapp", True, f"connector heartbeat {age_minutes:.1f}m old")

    # heartbeat stale and no known-bad status — the process is either gone
    # (down) or alive but not doing anything (zombie); tell them apart by
    # actually checking whether the pid is still running, since that's
    # exactly the question that couldn't be answered before this existed
    pid_text = WHATSAPP_PID_PATH.read_text().strip() if WHATSAPP_PID_PATH.exists() else ""
    if pid_text and pid_text.isdigit() and _pid_is_alive(int(pid_text)):
        return ChannelStatus(
            "whatsapp", False,
            f"ZOMBIE — process {pid_text} is still running but heartbeat is "
            f"{age_minutes:.1f}m old (threshold {_WHATSAPP_HEARTBEAT_THRESHOLD_MINUTES:.0f}m). "
            f"Kill it and restart: `taskkill /PID {pid_text} /F` then "
            "`node adapters/whatsapp/node/ingest.js`",
        )
    return ChannelStatus(
        "whatsapp", False,
        f"DOWN — no running process found (heartbeat {age_minutes:.1f}m old). "
        "Start it: `node adapters/whatsapp/node/ingest.js`",
    )


def _load_alert_state() -> dict:
    if ALERT_STATE_PATH.exists():
        return json.loads(ALERT_STATE_PATH.read_text())
    return {}


def _save_alert_state(state: dict) -> None:
    ALERT_STATE_PATH.write_text(json.dumps(state))


def _send_alert(message: str) -> None:
    """Console output always happens — that's the floor. ntfy.sh is the
    real destination, 2026-08-31: a push straight to phone + desktop, no
    account needed, just a topic name treated as a shared secret (anyone
    who knows it can read and post to it, so it's a long random string,
    not something guessable). A Slack-style webhook is also supported if
    MONITOR_ALERT_WEBHOOK_URL is ever set, but nothing currently uses it."""
    print(f"ALERT: {message}", file=sys.stderr)

    ntfy_topic = os.environ.get("MONITOR_NTFY_TOPIC")
    if ntfy_topic:
        req = urllib.request.Request(
            f"https://ntfy.sh/{ntfy_topic}",
            data=f"[pipe-health] {message}".encode(),
            headers={"Title": "Comms Platform Alert", "Priority": "high"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:  # noqa: BLE001 — alerting must never itself crash the monitor
            print(f"ALERT DELIVERY FAILED (ntfy): {e}", file=sys.stderr)

    webhook_url = os.environ.get("MONITOR_ALERT_WEBHOOK_URL")
    if webhook_url:
        payload = json.dumps({"text": f"[pipe-health] {message}"}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:  # noqa: BLE001 — alerting must never itself crash the monitor
            print(f"ALERT DELIVERY FAILED (webhook): {e}", file=sys.stderr)


def check_all(cur) -> list[ChannelStatus]:
    statuses: list[ChannelStatus] = [
        _check_message_staleness(cur, "outlook"),
        _check_message_staleness(cur, "linkedin"),
    ]
    statuses.append(_check_whatsapp_liveness())
    return statuses


def run() -> int:
    load_dotenv()

    try:
        conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    except Exception as e:  # noqa: BLE001 — report, don't crash the caller
        _send_alert(f"cannot reach store at all: {e}")
        return 1

    with conn, conn.cursor() as cur:
        statuses = check_all(cur)

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
