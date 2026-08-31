"""Ops dashboard: connect Outlook/LinkedIn/WhatsApp through a web page,
and run the same health checks scripts/monitor.py does in a background
thread so alerts fire whether or not this page is open. See
docs/superpowers/specs/2026-08-31-onboarding-dashboard-design.md.

Run: python scripts/onboarding/app.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from flask import Flask, jsonify, send_file

from adapters.outlook import client as outlook_client

# scripts/ isn't an installed package (only adapters* is, see
# pyproject.toml), so import its sibling monitor.py by path — same
# Path(__file__)-relative pattern used throughout this repo's adapters.
sys.path.insert(0, str(Path(__file__).parent.parent))
import monitor

_MONITOR_INTERVAL_SECONDS = 15 * 60


def _get_status_cursor():
    """A short-lived connection+cursor for one /status read — separate
    from monitor.run()'s own connection, which the background thread
    manages on its own schedule."""
    conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    return conn.cursor()


# in-memory only — a real device-code flow is inherently short-lived
# (expires in ~15 min), and this app has no other persistent store, so
# a restart simply means "connect again" rather than needing to survive
# a restart mid-flow
_outlook_state: dict = {"phase": "not_connected"}
_outlook_lock = threading.Lock()

# guards whatsapp_connect()'s check-then-spawn sequence the same way
# _outlook_lock guards the Outlook flow above. ingest.js only writes its
# own .pid file after it finishes starting up (after all its require()s),
# so there's a real window where a second /whatsapp/connect call would
# otherwise see .pid as still-missing-or-stale and spawn a duplicate
# "node ingest.js" — ingest.js has no protection against being
# double-started, and two processes sharing one .auth_state would
# corrupt it. _whatsapp_spawn_in_progress is set True right before
# Popen() and only cleared once a later call observes .pid pointing at
# a live process, so it can't be permanently stuck if the process dies
# before ever writing .pid — see whatsapp_connect() for that recovery.
_whatsapp_lock = threading.Lock()
_whatsapp_spawn_in_progress = False


def _whatsapp_pid_is_live() -> bool:
    pid_text = (
        monitor.WHATSAPP_PID_PATH.read_text().strip()
        if monitor.WHATSAPP_PID_PATH.exists() else ""
    )
    return bool(pid_text and pid_text.isdigit() and monitor._pid_is_alive(int(pid_text)))


def _clear_whatsapp_spawn_flag_if_live() -> None:
    """Called from /whatsapp/status (and implicitly whenever
    /whatsapp/connect re-checks liveness) so the in-progress flag doesn't
    permanently lock out future spawns after the connector it was tracking
    is confirmed alive and later dies."""
    global _whatsapp_spawn_in_progress
    if _whatsapp_spawn_in_progress:
        with _whatsapp_lock:
            if _whatsapp_spawn_in_progress and _whatsapp_pid_is_live():
                _whatsapp_spawn_in_progress = False


def _outlook_connect_worker() -> None:
    def on_device_code(flow: dict) -> None:
        with _outlook_lock:
            _outlook_state.update(
                phase="pending", code=flow["user_code"], url=flow["verification_uri"]
            )

    try:
        outlook_client.get_access_token(on_device_code=on_device_code)
        with _outlook_lock:
            _outlook_state.update(phase="connected")
    except Exception as e:  # noqa: BLE001 — any failure must reach a terminal
        # phase so /outlook/status can report it instead of hanging at
        # "starting" forever; only the message distinguishes "expired".
        with _outlook_lock:
            state = "expired" if "expired" in str(e) else "error"
            _outlook_state.update(phase=state, error=str(e))


def _background_monitor_loop() -> None:
    while True:
        try:
            monitor.run()
        except Exception as e:  # noqa: BLE001 — the loop must survive a bad check
            print(f"background monitor check failed: {e}", file=sys.stderr)
        time.sleep(_MONITOR_INTERVAL_SECONDS)


def create_app(testing: bool = False) -> Flask:
    load_dotenv()
    flask_app = Flask(__name__)

    @flask_app.get("/status")
    def status():
        try:
            cur = _get_status_cursor()
        except Exception as e:  # noqa: BLE001 — degrade, don't crash the route
            statuses = [
                monitor.ChannelStatus("outlook", False, f"cannot reach store: {e}"),
                monitor.ChannelStatus("linkedin", False, f"cannot reach store: {e}"),
                monitor._check_whatsapp_liveness(),
            ]
        else:
            try:
                statuses = monitor.check_all(cur)
            finally:
                cur.connection.close()
        return jsonify({s.channel: {"healthy": s.healthy, "detail": s.detail} for s in statuses})

    @flask_app.post("/outlook/connect")
    def outlook_connect():
        with _outlook_lock:
            if _outlook_state.get("phase") in ("starting", "pending"):
                return jsonify({"status": "already_in_progress"})
            _outlook_state.clear()
            _outlook_state["phase"] = "starting"
        threading.Thread(target=_outlook_connect_worker, daemon=True).start()
        return jsonify({"status": "started"})

    @flask_app.get("/outlook/status")
    def outlook_status():
        with _outlook_lock:
            phase = _outlook_state.get("phase", "not_connected")
            code = _outlook_state.get("code")
            url = _outlook_state.get("url")
            error = _outlook_state.get("error")

        if phase in ("not_connected", "starting"):
            return jsonify({"state": phase, "code": None, "url": None, "mailbox": None})
        if phase == "pending":
            return jsonify({"state": "pending", "code": code, "url": url, "mailbox": None})
        if phase == "connected":
            mailbox = os.environ.get("OUTLOOK_MAILBOX")
            return jsonify({"state": "connected", "code": None, "url": None, "mailbox": mailbox})
        # terminal failure states ("error", "expired") carry the message
        # from _outlook_connect_worker's except clause
        return jsonify({"state": phase, "code": None, "url": None, "mailbox": None, "error": error})

    @flask_app.get("/whatsapp/status")
    def whatsapp_status():
        _clear_whatsapp_spawn_flag_if_live()
        if not monitor.WHATSAPP_STATUS_PATH.exists():
            return jsonify({"state": "not_connected"})
        try:
            status = json.loads(monitor.WHATSAPP_STATUS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            # .status.json exists but is malformed — ingest.js's
            # writeStatus() does a non-atomic fs.writeFileSync, so a
            # concurrent read can catch it mid-write. Treat this the same
            # as "no status available yet" rather than 500ing the route,
            # mirroring monitor._check_whatsapp_liveness()'s handling of
            # this exact same file/failure mode.
            return jsonify({"state": "not_connected"})
        return jsonify(status)

    @flask_app.post("/whatsapp/connect")
    def whatsapp_connect():
        global _whatsapp_spawn_in_progress
        with _whatsapp_lock:
            if _whatsapp_pid_is_live():
                _whatsapp_spawn_in_progress = False
                return jsonify({"status": "already_running"})

            # a spawn from a rapid-fire earlier call may still be starting
            # up — ingest.js hasn't written .pid yet, so the liveness
            # check above can't see it. Don't spawn a second process on
            # top of it; it'll clear itself once .pid shows the process
            # alive (see _whatsapp_pid_is_live/_clear_whatsapp_spawn_flag_if_live).
            if _whatsapp_spawn_in_progress:
                return jsonify({"status": "already_running"})

            _whatsapp_spawn_in_progress = True
            subprocess.Popen(
                ["node", "ingest.js"],
                cwd=str(monitor._WHATSAPP_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return jsonify({"status": "started"})

    @flask_app.get("/whatsapp/qr.png")
    def whatsapp_qr():
        qr_path = monitor._WHATSAPP_DIR / "qr.png"
        if not qr_path.exists():
            return jsonify({"error": "no QR available yet"}), 404
        return send_file(qr_path, mimetype="image/png", max_age=0)

    if not testing:
        thread = threading.Thread(target=_background_monitor_loop, daemon=True)
        thread.start()

    return flask_app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
