"""LinkedIn adapter entrypoint. Requires a saved session (run login.py
first). No member id to configure — client.py derives "who am I" straight
from LinkedIn's own response payloads (see _self_urn_from_conversation_urn),
which replaced an earlier LINKEDIN_MEMBER_ID scheme that turned out to
compare the wrong id shape entirely (found 2026-08-28 against a real
message: it never matched, so direction was silently always wrong).

Run: python -m adapters.linkedin.sync
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from ..envelope import Direction
from ..store_writer import upsert
from .client import STORAGE_STATE_PATH
from .client import run as fetch_envelopes
from .session_limit import SessionLimitExceeded

# Answers a question monitor.py couldn't before: "did the sync itself
# actually run and finish" is a different question from "did any new
# messages land" — a quiet LinkedIn inbox for a few days is genuinely
# healthy, and conflating the two meant a working pipeline reported
# unhealthy every time nobody happened to message. See scripts/monitor.py's
# _check_linkedin_liveness for the read side of this file.
STATUS_PATH = Path(__file__).parent / ".sync_status.json"


def _write_status(state: str, detail: str) -> None:
    STATUS_PATH.write_text(json.dumps({
        "state": state,
        "detail": detail,
        "at": datetime.now(UTC).isoformat(),
    }))


def _self_handle(env) -> str:
    # store_writer.upsert() needs to know which handle is "you" to set
    # identity.is_self correctly — client.py already computed direction
    # against exactly this, so it's recoverable from the envelope itself
    # without re-deriving it: outbound means from_handle is you, inbound
    # means the (single) to_handle is you (see client.py's _to_envelope).
    if env.direction == Direction.outbound:
        return env.from_handle
    return env.to_handles[0] if env.to_handles else ""


def run() -> None:
    load_dotenv()

    if not STORAGE_STATE_PATH.exists():
        _write_status(
            "error",
            f"no saved session at {STORAGE_STATE_PATH} — run "
            "`python -m adapters.linkedin.login` first",
        )
        raise RuntimeError(
            f"no saved session at {STORAGE_STATE_PATH} — run "
            "`python -m adapters.linkedin.login` first"
        )

    count = 0
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            # commit as each message lands, not once at the end — a scrape
            # session can span many minutes across many threads (§13's
            # human-paced delays add up), and a crash or a killed process
            # partway through should not throw away everything pulled so far
            try:
                for env in fetch_envelopes(headless=True):
                    upsert(conn, env, _self_handle(env))
                    conn.commit()
                    count += 1
            except SessionLimitExceeded as e:
                # expected, not a bug: §13's daily cap doing exactly its
                # job. A scheduler calling this too often (someone in a
                # hurry pointing cron at every 5 minutes, say) should see
                # a clean refusal here, not a stack trace — and every
                # call after today's cap is spent is a local file check
                # before this point, no LinkedIn traffic at all, so
                # calling it again in a tight loop costs nothing further.
                # "capped" is its own state, not "error" — the mechanism
                # itself worked fine, it deliberately declined to run.
                print(f"stopped: {e}")
                print(f"synced {count} messages before hitting the limit")
                _write_status("capped", f"daily session limit reached — synced {count} before stopping")
                return
    except Exception as e:  # record the real failure, then let it surface
        _write_status("error", f"sync failed: {e}")
        raise

    _write_status("ok", f"synced {count} messages")
    print(f"synced {count} messages")


if __name__ == "__main__":
    run()
