"""LinkedIn adapter entrypoint. Requires a saved session (run login.py
first). No member id to configure — client.py derives "who am I" straight
from LinkedIn's own response payloads (see _self_urn_from_conversation_urn),
which replaced an earlier LINKEDIN_MEMBER_ID scheme that turned out to
compare the wrong id shape entirely (found 2026-08-28 against a real
message: it never matched, so direction was silently always wrong).

Run: python -m adapters.linkedin.sync
"""

from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv

from ..envelope import Direction
from ..store_writer import upsert
from .client import STORAGE_STATE_PATH
from .client import run as fetch_envelopes


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
        raise RuntimeError(
            f"no saved session at {STORAGE_STATE_PATH} — run "
            "`python -m adapters.linkedin.login` first"
        )

    count = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        # commit as each message lands, not once at the end — a scrape
        # session can span many minutes across many threads (§13's
        # human-paced delays add up), and a crash or a killed process
        # partway through should not throw away everything pulled so far
        for env in fetch_envelopes(headless=True):
            upsert(conn, env, _self_handle(env))
            conn.commit()
            count += 1

    print(f"synced {count} messages")


if __name__ == "__main__":
    run()
