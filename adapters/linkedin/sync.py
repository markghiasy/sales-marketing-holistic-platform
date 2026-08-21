"""LinkedIn adapter entrypoint. Requires a saved session (run login.py
first) and your own member id in LINKEDIN_MEMBER_ID — find it by opening
your own profile and reading the id out of the URL (/in/<this part>).

Run: python -m adapters.linkedin.sync
"""

from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv

from ..store_writer import upsert
from .client import STORAGE_STATE_PATH, _to_profile_urn, run as fetch_envelopes


def run() -> None:
    load_dotenv()

    if not STORAGE_STATE_PATH.exists():
        raise RuntimeError(
            f"no saved session at {STORAGE_STATE_PATH} — run "
            "`python -m adapters.linkedin.login` first"
        )

    self_member_id = os.environ["LINKEDIN_MEMBER_ID"]
    self_urn = _to_profile_urn(self_member_id)  # envelopes carry full URNs
                                                 # as handles, not the bare
                                                 # id — upsert must compare
                                                 # against the same format

    count = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        # commit as each message lands, not once at the end — a scrape
        # session can span many minutes across many threads (§13's
        # human-paced delays add up), and a crash or a killed process
        # partway through should not throw away everything pulled so far
        for env in fetch_envelopes(self_member_id, headless=True):
            upsert(conn, env, self_urn)
            conn.commit()
            count += 1

    print(f"synced {count} messages")  # noqa: T201


if __name__ == "__main__":
    run()
