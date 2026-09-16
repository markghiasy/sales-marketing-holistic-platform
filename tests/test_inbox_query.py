from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg

from adapters.inbox_query import list_conversations


def _make_identity(cur, channel: str, handle: str, is_self: bool = False, display_name: str | None = None) -> str:
    cur.execute(
        "insert into identity (channel, handle, is_self, display_name) values (%s, %s, %s, %s) returning id",
        (channel, handle, is_self, display_name),
    )
    return str(cur.fetchone()[0])


def _make_thread(cur, channel: str, last_read_at=None) -> str:
    external_id = f"thread-{uuid.uuid4().hex}"
    cur.execute(
        "insert into thread (channel, external_id, last_read_at) values (%s, %s, %s) returning id",
        (channel, external_id, last_read_at),
    )
    return str(cur.fetchone()[0])


def _make_message(cur, thread_id, channel, direction, from_identity_id, participant_ids, sent_at, body_text="hi"):
    external_id = f"msg-{uuid.uuid4().hex}"
    cur.execute(
        """
        insert into message (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, raw)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, psycopg.types.json.Json({})),
    )
    message_id = str(cur.fetchone()[0])
    for identity_id in participant_ids:
        role = "from" if identity_id == from_identity_id else "to"
        cur.execute(
            "insert into message_participant (message_id, identity_id, role) values (%s, %s, %s)",
            (message_id, identity_id, role),
        )
    # keep thread.last_message_at consistent with what a real sync would set
    cur.execute("update thread set last_message_at = %s where id = %s", (sent_at, thread_id))
    return message_id


class TestListConversations:
    def test_unread_when_new_message_after_last_read(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test Contact")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now - timedelta(days=1))
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)

        rows = list_conversations(cur)

        row = next(r for r in rows if r.person_key == contact_id)
        assert row.unread is True

    def test_read_when_last_read_after_last_message(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test Contact")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now + timedelta(minutes=1))
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)

        rows = list_conversations(cur)

        row = next(r for r in rows if r.person_key == contact_id)
        assert row.unread is False

    def test_unanswered_when_last_message_inbound(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test Contact")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now, body_text="need this by friday")

        rows = list_conversations(cur)

        row = next(r for r in rows if r.person_key == contact_id)
        assert row.unanswered is True
        assert row.summary == "need this by friday"  # no ai_brief row yet -> falls back to snippet
        assert row.channel == "outlook"

    def test_answered_when_last_message_outbound(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test Contact")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now - timedelta(hours=1))
        _make_message(cur, thread_id, "outlook", "outbound", self_id, [self_id, contact_id], now)

        rows = list_conversations(cur)

        row = next(r for r in rows if r.person_key == contact_id)
        assert row.unanswered is False

    def test_ai_brief_overrides_summary_topic_urgency(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test Contact")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now, body_text="raw text")
        cur.execute(
            """
            insert into ai_brief (person_key, summary, context, topic, graph, urgency, model, prompt_version)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (contact_id, "Needs X by Friday.", psycopg.types.json.Json(["a sentence"]), "Contract Request",
             psycopg.types.json.Json({"org": None, "people": []}), 3, "test-model", "v1"),
        )

        rows = list_conversations(cur)

        row = next(r for r in rows if r.person_key == contact_id)
        assert row.summary == "Needs X by Friday."
        assert row.topic == "Contract Request"
        assert row.urgency == 3
        assert row.has_draft is False  # this pass never produces a real draft

    def test_no_ai_brief_row_falls_back_sensibly(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test Contact")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now, body_text="raw text")

        rows = list_conversations(cur)

        row = next(r for r in rows if r.person_key == contact_id)
        assert row.topic == "General"
        assert row.urgency == 2
