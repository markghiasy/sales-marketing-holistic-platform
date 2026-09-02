"""Pipeline health monitor (build plan §3, "Elsewhere" row — pipe-health
monitoring). Supersedes pipe_health.py's single "is anything reachable"
check with a per-channel staleness check and an actual alert, meant to run
on a schedule rather than by hand.

Three different kinds of signal, deliberately not conflated:

- Outlook runs as a one-shot sync script on a 10-minute schedule — for
  this, "healthy" still means "the last sync ran recently and wrote
  something," approximated by max(message.ingested_at). That's a
  reasonable proxy at a 10-minute cadence: a real mailbox is rarely
  quiet that long, so staleness is a fair stand-in for "did the last
  run work."
- LinkedIn runs 4x/day — quiet for a day or two is completely normal
  (nobody messaged), so the same message-staleness proxy used for
  Outlook produces false alarms here. Found 2026-09-02: a real,
  successfully-completed sync reported "unhealthy" for over two days
  straight because the inbox genuinely had no new messages, not because
  anything was broken. Fixed by checking a different signal entirely:
  adapters/linkedin/sync.py now writes its own .sync_status.json after
  every run (ok/capped/error, with the real detail), independent of
  whether anything new was found — this checks "did the mechanism run"
  the same way the WhatsApp heartbeat checks "is the connector alive,"
  instead of asking a question a quiet inbox can't answer.
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
_LINKEDIN_DIR = Path(__file__).parent.parent / "adapters" / "linkedin"
LINKEDIN_SYNC_STATUS_PATH = _LINKEDIN_DIR / ".sync_status.json"
ALERT_STATE_PATH = Path(__file__).parent / ".monitor_alert_state.json"

# Staleness thresholds per channel, in hours — overridable via env so
# these can tighten without a code change. Outlook's is generous
# relative to its 10-minute cadence on purpose (catches "scheduling
# stopped entirely," not "one run was a few minutes late"). LinkedIn's
# is no longer message-based (see module docstring) — this is instead
# "how long since the sync mechanism itself last ran," sized to the
# 4x/day schedule (~9am/12:30/3:30/7pm): the longest normal gap is the
# overnight one (~7pm to ~9am, ~14h), so 20h gives room for jitter and
# one missed slot before flagging without also masking a genuinely
# stopped scheduler for days.
_DEFAULT_THRESHOLDS_HOURS = {
    "outlook": 24.0,
    "linkedin_run": 20.0,
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


def _check_linkedin_liveness() -> ChannelStatus:
    """Checks whether the sync mechanism itself last ran successfully —
    a separate question from whether any new messages showed up, which
    a quiet LinkedIn inbox can go days without answering "yes" to even
    when nothing is broken. See adapters/linkedin/sync.py's
    _write_status for the write side of this file."""
    if not LINKEDIN_SYNC_STATUS_PATH.exists():
        return ChannelStatus(
            "linkedin", False,
            "never run yet, or ran before this status file existed — "
            "run it: `python -m adapters.linkedin.sync`",
        )

    try:
        status = json.loads(LINKEDIN_SYNC_STATUS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return ChannelStatus("linkedin", False, f"couldn't read sync status: {e}")

    state = status.get("state")
    detail = status.get("detail", "no detail")
    at_text = status.get("at")

    if state == "error":
        return ChannelStatus("linkedin", False, f"last sync failed — {detail}")

    if not at_text:
        return ChannelStatus("linkedin", False, "sync status file missing a timestamp")

    try:
        at = datetime.fromisoformat(at_text)
    except ValueError:
        return ChannelStatus("linkedin", False, f"sync status has an unparseable timestamp: {at_text}")

    age_hours = (datetime.now(UTC) - at).total_seconds() / 3600
    threshold = _threshold_hours("linkedin_run")
    if age_hours > threshold:
        return ChannelStatus(
            "linkedin", False,
            f"last successful run {age_hours:.1f}h ago, threshold is "
            f"{threshold:.0f}h — the schedule may have stopped firing "
            f"(last: {detail})",
        )

    # "capped" (hit the daily session limit) is still a healthy sign —
    # the mechanism ran, made a deliberate choice, and exited clean; see
    # sync.py's own comment on why that's not a failure.
    return ChannelStatus("linkedin", True, f"last run {age_hours:.1f}h ago — {detail}")


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


_WHATSAPP_AUTO_HEAL_TIMEOUT_SECONDS = 30.0
_WHATSAPP_AUTO_HEAL_POLL_INTERVAL_SECONDS = 2.0


def _start_whatsapp_detached() -> None:
    """Launches ingest.js independent of this process's own lifetime —
    monitor.py exits after every check, so a plain subprocess.Popen
    whose child dies with its parent would defeat the point of
    auto-healing. DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP is the
    Windows-specific way to fully decouple the child from its launcher —
    the same problem hit repeatedly running ingest.js as a Claude Code
    background task: the child died whenever the launching session did,
    even though nobody asked for that."""
    subprocess.Popen(
        ["node", "ingest.js"],
        cwd=str(_WHATSAPP_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def _attempt_whatsapp_auto_heal(status: ChannelStatus) -> tuple[ChannelStatus, bool]:
    """Only called for DOWN/ZOMBIE — the two states where "restart the
    process" is the actual, complete fix and needs no human. logged_out
    and qr_pending are deliberately excluded: no amount of automation can
    complete a WhatsApp QR pairing, that needs a real phone in a real
    hand. Returns the post-attempt status and whether healing succeeded,
    so the caller can pick the right alert (quiet success note vs. an
    urgent "I tried and it's still broken" push)."""
    if status.detail.startswith("ZOMBIE"):
        pid_text = WHATSAPP_PID_PATH.read_text().strip() if WHATSAPP_PID_PATH.exists() else ""
        if pid_text.isdigit():
            subprocess.run(
                ["taskkill", "/PID", pid_text, "/F"], capture_output=True, check=False
            )

    try:
        _start_whatsapp_detached()
    except OSError as e:
        # e.g. node isn't on PATH — auto-heal genuinely can't proceed;
        # report this as a failed heal rather than letting the whole
        # monitor run crash over it
        return ChannelStatus("whatsapp", False, f"auto-heal couldn't start node: {e}"), False

    deadline = time.time() + _WHATSAPP_AUTO_HEAL_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(_WHATSAPP_AUTO_HEAL_POLL_INTERVAL_SECONDS)
        recheck = _check_whatsapp_liveness()
        if recheck.healthy:
            return recheck, True
    return _check_whatsapp_liveness(), False


def _load_alert_state() -> dict:
    if ALERT_STATE_PATH.exists():
        return json.loads(ALERT_STATE_PATH.read_text())
    return {}


def _save_alert_state(state: dict) -> None:
    ALERT_STATE_PATH.write_text(json.dumps(state))


def _send_alert(message: str, priority: str = "high") -> None:
    """Console output always happens — that's the floor. ntfy.sh is the
    real destination, 2026-08-31: a push straight to phone + desktop, no
    account needed, just a topic name treated as a shared secret (anyone
    who knows it can read and post to it, so it's a long random string,
    not something guessable). A Slack-style webhook is also supported if
    MONITOR_ALERT_WEBHOOK_URL is ever set, but nothing currently uses it.

    priority — 2026-09-01, added for auto-heal reporting: a successful
    self-heal is informational ("default"), a failed one is "urgent" so
    it's visually distinct from routine alerts and from a heal that
    quietly worked — the two outcomes need different reactions from a
    human and shouldn't look the same on a phone lock screen."""
    print(f"ALERT: {message}", file=sys.stderr)

    ntfy_topic = os.environ.get("MONITOR_NTFY_TOPIC")
    if ntfy_topic:
        req = urllib.request.Request(
            f"https://ntfy.sh/{ntfy_topic}",
            data=f"[pipe-health] {message}".encode(),
            headers={"Title": "Comms Platform Alert", "Priority": priority},
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
    statuses: list[ChannelStatus] = [_check_message_staleness(cur, "outlook")]
    statuses.append(_check_linkedin_liveness())
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
        # Auto-heal only applies to whatsapp's DOWN/ZOMBIE — the two
        # states where restarting the process is the complete fix and
        # needs no human. This runs before the healthy/unhealthy branch
        # below so a successful heal reports OK like any other healthy
        # check, not as a disguised failure.
        heal_attempted = False
        healed = False
        if (
            not status.healthy
            and status.channel == "whatsapp"
            and (status.detail.startswith("DOWN") or status.detail.startswith("ZOMBIE"))
        ):
            print(f"AUTO-HEAL attempting: {status.detail}")
            heal_attempted = True
            status, healed = _attempt_whatsapp_auto_heal(status)

        if status.healthy:
            print(f"OK   {status.channel}: {status.detail}")
            alert_state.pop(status.channel, None)  # recovered — reset cooldown
            if healed:
                # always report a successful self-heal, regardless of
                # cooldown state — this is a one-off "it broke, I fixed
                # it" note, not a repeated failure that needs suppressing
                _send_alert(f"whatsapp auto-healed — {status.detail}", priority="default")
            continue

        any_unhealthy = True
        print(f"FAIL {status.channel}: {status.detail}")
        last_alerted = alert_state.get(status.channel, 0)
        if now - last_alerted > _ALERT_COOLDOWN_HOURS * 3600:
            if heal_attempted:
                # a self-heal was attempted and failed — escalate above
                # the normal "high" priority so it's visually distinct
                # from routine alerts on a phone lock screen
                _send_alert(
                    f"whatsapp unhealthy — auto-heal attempted and FAILED — {status.detail}",
                    priority="urgent",
                )
            else:
                _send_alert(f"{status.channel} unhealthy — {status.detail}")
            alert_state[status.channel] = now

    _save_alert_state(alert_state)
    return 1 if any_unhealthy else 0


if __name__ == "__main__":
    sys.exit(run())
