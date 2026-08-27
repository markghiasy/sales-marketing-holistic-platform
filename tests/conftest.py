"""Shared test fixtures.

`db_conn` connects to the local docker-compose Postgres (not the hosted
Supabase instance — tests should never touch real production data) and
wraps each test in a transaction that's rolled back at teardown, never
committed. store_writer.upsert() itself never calls commit() (callers
own that), so this genuinely isolates every test: whatever a test
inserts is invisible to any other connection and gone by the next test,
without ever touching the real rows already in this local database.
"""

from __future__ import annotations

import psycopg
import pytest
from dotenv import load_dotenv

# Deliberately not DATABASE_URL from .env — that now points at the
# hosted Supabase instance with real data. Tests always target the
# local docker-compose Postgres, which must be running (docker compose
# up -d in the repo root) for the DB-dependent tests to pass.
_LOCAL_TEST_DATABASE_URL = "postgresql://comms:comms@localhost:5432/comms"


@pytest.fixture
def db_conn():
    load_dotenv()
    conn = psycopg.connect(_LOCAL_TEST_DATABASE_URL)
    try:
        yield conn
    finally:
        conn.rollback()  # never commit — nothing a test does persists
        conn.close()
