"""Regressions for the test database boundary, not production databases."""

import os

import conftest
import psycopg
import pytest


def test_database_url_never_falls_back_to_application_environment(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/customer_data")
    with pytest.raises(pytest.UsageError, match="TEST_DATABASE_URL"):
        conftest.read_test_database_url()


@pytest.mark.parametrize("url", [
    "postgresql://production.invalid/comms_test",
    "postgresql://localhost/comms",
    "postgresql://localhost/postgres",
])
def test_database_url_rejects_nonlocal_or_nontest_database(monkeypatch, url):
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    with pytest.raises(pytest.UsageError):
        conftest.read_test_database_url()


def test_database_url_honors_explicit_disposable_port(monkeypatch):
    url = "postgresql://tester:example@127.0.0.1:55432/comms_test"
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    assert conftest.read_test_database_url() == url


def test_committed_seed_is_visible_to_independent_application_connection(db_conn):
    row_id = db_conn.execute(
        "insert into identity(channel, handle) values ('outlook', 'fixture@example.test') returning id"
    ).fetchone()[0]
    db_conn.commit()
    with psycopg.connect(os.environ["DATABASE_URL"]) as other:
        assert other.info.backend_pid != db_conn.info.backend_pid
        assert other.execute("select handle from identity where id = %s", (row_id,)).fetchone() == (
            "fixture@example.test",
        )


def test_schema_cleanup_removes_committed_data_after_failure(test_database_url):
    schema = None
    with (
        pytest.raises(RuntimeError, match="deliberate test failure"),
        conftest.isolated_test_schema(test_database_url) as url,
    ):
        with psycopg.connect(url) as conn:
            schema = conn.execute("select current_schema()").fetchone()[0]
            conn.execute("insert into identity(channel, handle) values ('outlook', 'leak@example.test')")
        raise RuntimeError("deliberate test failure")
    with psycopg.connect(test_database_url) as conn:
        assert conn.execute("select 1 from pg_namespace where nspname = %s", (schema,)).fetchone() is None
