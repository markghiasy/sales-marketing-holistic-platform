"""Scheduled-task entrypoint for LinkedIn sync.

Mark's 2026-08-30 cadence call: 4 sessions/day at fixed clock times
(~9am / 12:30 / 3:30 / 7pm) with jitter. Windows Task Scheduler triggers
this at each of those four times; the jitter itself lives here rather
than in Task Scheduler's own trigger config, so the same script works
unchanged if the scheduler is ever swapped for cron/systemd on a hosted
box later.

Run: python scripts/run_linkedin_sync.py
"""

from __future__ import annotations

import random
import time

from adapters.linkedin.config import load as load_config
from adapters.linkedin.sync import run


def main() -> None:
    jitter_seconds = load_config().session_jitter_minutes * 60
    delay = random.uniform(0, jitter_seconds)
    print(f"jittering {delay / 60:.1f} min before starting")
    time.sleep(delay)
    run()


if __name__ == "__main__":
    main()
