"""Explicit disposable test DB; never load the application .env.

Each DB test owns a migrated schema. Normal tests roll back; integration
tests may commit so independent app connections see seeds. Dropping only
that generated schema cleans up both kinds of writes, even after failures.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def read_test_database_url():
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        raise pytest.UsageError(
            "Set TEST_DATABASE_URL to a disposable local database ending in _test or _tests "
            "(or starting with test_). DATABASE_URL and .env are never used by DB fixtures."
        )
    try:
        params = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        raise pytest.UsageError("TEST_DATABASE_URL is not a valid PostgreSQL connection URL") from None
    local = {"localhost", "127.0.0.1", "::1"}
    name = params.get("dbname", "")
    if (
        params.get("host") not in local
        or (params.get("hostaddr") and params["hostaddr"] not in {"127.0.0.1", "::1"})
        or not (name.startswith("test_") or name.endswith(("_test", "_tests")))
    ):
        raise pytest.UsageError("TEST_DATABASE_URL must name a disposable test database on loopback")
    return url


@pytest.fixture(scope="session")
def test_database_url():
    url = read_test_database_url()
    # Pin the address too: unrelated PGHOSTADDR must not override the local host.
    host = conninfo_to_dict(url)["host"]
    return make_conninfo(url, hostaddr="::1" if host == "::1" else "127.0.0.1", connect_timeout=5)


@contextlib.contextmanager
def isolated_test_schema(url):
    schema = "pytest_" + uuid.uuid4().hex
    scoped_url = make_conninfo(url, options=f"-csearch_path={schema}")
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("create extension if not exists pgcrypto with schema public")
        admin.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
        try:
            with psycopg.connect(scoped_url) as migration_conn:
                for migration in sorted((Path(__file__).parents[1] / "db" / "migrations").glob("*.sql")):
                    migration_conn.execute(migration.read_text(encoding="utf-8"))
            yield scoped_url
        finally:
            admin.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))


@pytest.fixture
def isolated_database_url(test_database_url, monkeypatch):
    with isolated_test_schema(test_database_url) as url:
        monkeypatch.setenv("DATABASE_URL", url)
        yield url


@pytest.fixture
def db_conn(isolated_database_url):
    conn = psycopg.connect(isolated_database_url)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
