"""Tests for adapters/store_writer.py — the one place every channel's
upsert goes through. Needs a real database (uses the local docker-compose
Postgres, see conftest.py); each test runs in a transaction that's rolled
back, so nothing here ever touches the real rows already in that
database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from adapters.envelope import Channel, Direction, Envelope
from adapters.store_writer import upsert


def _make_envelope(**overrides) -> Envelope:
    unique = uuid.uuid4().hex[:12]
    base = {
        "channel": Channel.outlook,
        "external_id": f"test-msg-{unique}",
        "thread_external_id": f"test-thread-{unique}",
        "direction": Direction.inbound,
        "sent_at": datetime.now(UTC),
        "from_handle": "sender@example.com",
        "to_handles": ["me@example.com"],
        "body_text": "hello",
    }
    base.update(overrides)
    return Envelope(**base)


class TestUpsert:
    def test_inserts_a_new_message(self, db_conn: psycopg.Connection):
        env = _make_envelope()
        upsert(db_conn, env, self_handle="me@example.com")

        cur = db_conn.cursor()
        cur.execute(
            "select body_text from message where channel = %s and external_id = %s",
            (env.channel.value, env.external_id),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "hello"

    def test_idempotent_on_rerun(self, db_conn: psycopg.Connection):
        env = _make_envelope()
        upsert(db_conn, env, self_handle="me@example.com")
        upsert(db_conn, env, self_handle="me@example.com")  # same external_id again

        cur = db_conn.cursor()
        cur.execute(
            "select count(*) from message where channel = %s and external_id = %s",
            (env.channel.value, env.external_id),
        )
        assert cur.fetchone()[0] == 1

    def test_creates_message_participant_edges(self, db_conn: psycopg.Connection):
        env = _make_envelope(to_handles=["a@example.com", "b@example.com"])
        upsert(db_conn, env, self_handle="me@example.com")

        cur = db_conn.cursor()
        cur.execute(
            """
            select role, i.handle from message_participant mp
            join message m on m.id = mp.message_id
            join identity i on i.id = mp.identity_id
            where m.channel = %s and m.external_id = %s
            order by role, i.handle
            """,
            (env.channel.value, env.external_id),
        )
        rows = cur.fetchall()
        assert ("from", "sender@example.com") in rows
        assert ("to", "a@example.com") in rows
        assert ("to", "b@example.com") in rows

    def test_marks_self_handle_identity(self, db_conn: psycopg.Connection):
        env = _make_envelope(
            direction=Direction.outbound,
            from_handle="me@example.com",
            to_handles=["other@example.com"],
        )
        upsert(db_conn, env, self_handle="me@example.com")

        cur = db_conn.cursor()
        cur.execute(
            "select is_self from identity where channel = %s and handle = %s",
            (env.channel.value, "me@example.com"),
        )
        assert cur.fetchone()[0] is True

    def test_backfills_display_name_on_rerun_for_to_only_contact(
        self, db_conn: psycopg.Connection
    ):
        # regression test for the exact bug store_writer.py's own comments
        # describe: a "to"-only contact's name couldn't be backfilled on
        # rerun because the function used to return early on an existing
        # message, before the to-identity loop ran at all
        env1 = _make_envelope(to_handles=["contact@example.com"], to_display_names=[None])
        upsert(db_conn, env1, self_handle="me@example.com")

        env2 = _make_envelope(
            external_id=env1.external_id,  # same message — triggers the early-return path
            to_handles=["contact@example.com"],
            to_display_names=["Real Name"],
        )
        upsert(db_conn, env2, self_handle="me@example.com")

        cur = db_conn.cursor()
        cur.execute(
            "select display_name from identity where channel = %s and handle = %s",
            (env1.channel.value, "contact@example.com"),
        )
        assert cur.fetchone()[0] == "Real Name"

    def test_empty_string_display_name_does_not_block_later_backfill(
        self, db_conn: psycopg.Connection
    ):
        # regression test for the other bug store_writer.py's comments
        # describe: an empty string satisfies SQL's "is not null" check,
        # which would have permanently blocked a real name from ever
        # being backfilled later
        env1 = _make_envelope(from_display_name="")
        upsert(db_conn, env1, self_handle="me@example.com")

        env2 = _make_envelope(
            external_id="different-message-" + uuid.uuid4().hex[:8],
            from_handle=env1.from_handle,
            from_display_name="Real Name",
        )
        upsert(db_conn, env2, self_handle="me@example.com")

        cur = db_conn.cursor()
        cur.execute(
            "select display_name from identity where channel = %s and handle = %s",
            (env1.channel.value, env1.from_handle),
        )
        assert cur.fetchone()[0] == "Real Name"


@pytest.fixture(autouse=True, scope="module")
def _require_local_db():
    """Skip this whole file with a clear message if the local
    docker-compose Postgres isn't up, instead of every test failing with
    a raw connection-refused traceback."""
    try:
        conn = psycopg.connect(
            "postgresql://comms:comms@localhost:5432/comms", connect_timeout=3
        )
        conn.close()
    except psycopg.OperationalError:
        pytest.skip(
            "local docker-compose Postgres isn't reachable — run "
            "`docker compose up -d` in the repo root first"
        )
