"""Ops dashboard: connect Outlook/LinkedIn/WhatsApp through a web page,
and run the same health checks scripts/monitor.py does in a background
thread so alerts fire whether or not this page is open. See
docs/superpowers/specs/2026-08-31-onboarding-dashboard-design.md.

Run: python scripts/onboarding/app.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from flask import Flask, jsonify

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
        cur = _get_status_cursor()
        try:
            statuses = monitor.check_all(cur)
        finally:
            cur.connection.close()
        return jsonify({s.channel: {"healthy": s.healthy, "detail": s.detail} for s in statuses})

    if not testing:
        thread = threading.Thread(target=_background_monitor_loop, daemon=True)
        thread.start()

    return flask_app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
