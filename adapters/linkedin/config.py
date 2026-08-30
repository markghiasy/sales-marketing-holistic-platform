"""Rate/volume parameters for the LinkedIn adapter.

Build plan §13 rule 2: "Rate and volume parameters are fixed; changing one
needs written sign-off in advance." These are NOT tuned yet — the numbers
below are a conservative placeholder (roughly human browsing pace) so the
adapter has something to run with. Mark needs to give the real numbers
before this touches his account; until then, don't loosen these without
asking.

Every value is overridable via env so tightening (never loosening without
sign-off) doesn't require a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimits:
    min_delay_seconds: float = 3.0
    max_delay_seconds: float = 8.0
    max_pages_per_session: int = 20
    max_sessions_per_day: int = 4
    # both lists (conversations, and each thread's message history) are
    # virtualized — only what's scrolled into view is ever in the DOM/fired
    # as a network response. These bound how hard we scroll to pull older
    # history before giving up, independent of max_pages_per_session.
    max_scroll_attempts: int = 10
    scroll_pause_seconds: float = 1.5
    # jitter applied by scripts/run_linkedin_sync.py before a scheduled
    # session starts — not one of §13 rule 2's fixed rate/volume params
    # (it doesn't touch how the session itself behaves once running), so
    # this one's tunable without a sign-off round trip. Mark's 2026-08-30
    # cadence call specified 4 sessions/day at fixed clock times "with
    # jitter"; a flat 15-minute default keeps every scheduled run inside
    # the same half-hour window as its neighbour on the timetable.
    session_jitter_minutes: float = 15.0


def load() -> RateLimits:
    # os.environ.get()'s default is typed str | None — pass string
    # defaults, not the numeric literals, and convert after
    return RateLimits(
        min_delay_seconds=float(os.environ.get("LINKEDIN_MIN_DELAY_S", "3.0")),
        max_delay_seconds=float(os.environ.get("LINKEDIN_MAX_DELAY_S", "8.0")),
        max_pages_per_session=int(os.environ.get("LINKEDIN_MAX_PAGES_PER_SESSION", "20")),
        max_sessions_per_day=int(os.environ.get("LINKEDIN_MAX_SESSIONS_PER_DAY", "4")),
        max_scroll_attempts=int(os.environ.get("LINKEDIN_MAX_SCROLL_ATTEMPTS", "10")),
        scroll_pause_seconds=float(os.environ.get("LINKEDIN_SCROLL_PAUSE_S", "1.5")),
        session_jitter_minutes=float(os.environ.get("LINKEDIN_SESSION_JITTER_MINUTES", "15.0")),
    )
