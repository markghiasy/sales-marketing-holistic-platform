"""Enforces §13 rule 2's daily session cap for the LinkedIn live-scraping
path — found 2026-08-28 that `max_sessions_per_day` in config.py was
defined and loaded but never actually checked anywhere: nothing stopped
a run over the limit, it was just a number sitting in a dataclass. If
someone points a scheduler at `sync.py` every 5 minutes (say, in a hurry,
not thinking about it), this is what's supposed to catch that — clean
refusal after the 4th session of the day, not silent overuse, and not an
ugly crash either. A tight retry loop hitting this repeatedly still costs
nothing further: every call after the day's cap is a fast local check,
zero network traffic, before a browser ever opens.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

STATE_PATH = Path(__file__).parent / ".session_count.json"


class SessionLimitExceeded(RuntimeError):
    pass


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def record_session(max_sessions_per_day: int) -> None:
    """Call once per scraping session, before opening a browser. Raises
    SessionLimitExceeded (not a bare crash — the message names the actual
    constraint) if today's count is already at the cap; otherwise records
    this session and lets the caller proceed."""
    state = _load_state()
    today = _today()

    if state.get("date") != today:
        state = {"date": today, "count": 0}

    if state["count"] >= max_sessions_per_day:
        raise SessionLimitExceeded(
            f"LinkedIn daily session limit reached ({state['count']}/{max_sessions_per_day} "
            f"today, UTC). Locked by Mark per §13 rule 2 — no loosening without his "
            f"written sign-off. Resets at UTC midnight."
        )

    state["count"] += 1
    STATE_PATH.write_text(json.dumps(state))
