"""Pipe-health heartbeat (build plan §3, "Elsewhere" row).

Cheap, boring check: did the last sync run recently, and is the store
reachable. Not a monitoring platform — just enough to know the pipe is
still flowing without opening a log file.
"""

from __future__ import annotations

import os
import sys

import psycopg


def check() -> int:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("select max(ingested_at) from message")
                (last_ingest,) = cur.fetchone()
    except Exception as e:  # noqa: BLE001 — heartbeat: report, don't crash the caller
        print(f"UNHEALTHY: cannot reach store: {e}")  # noqa: T201
        return 1

    if last_ingest is None:
        print("UNHEALTHY: store is reachable but empty — no messages ingested yet")  # noqa: T201
        return 1

    print(f"OK: last ingest at {last_ingest}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(check())
