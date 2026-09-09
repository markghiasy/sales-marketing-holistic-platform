# tests/test_reply_signal.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg

from adapters.reply_signal import reply_signal


def _make_identity(cur, channel: str, handle: str, is_self: bool = False) -> str:
    cur.execute(
        "insert into identity (channel, handle, is_self) values (%s, %s, %s) returning id",
        (channel, handle, is_self),
    )
    return str(cur.fetchone()[0])


def _make_thread(cur, channel: str) -> str:
    external_id = f"thread-{uuid.uuid4().hex}"
    cur.execute(
        "insert into thread (channel, external_id) values (%s, %s) returning id",
        (channel, external_id),
    )
    return str(cur.fetchone()[0])


def _make_message(
    cur, thread_id: str, channel: str, direction: str, from_identity_id: str,
    participant_ids: list[str], sent_at: datetime,
) -> str:
    external_id = f"msg-{uuid.uuid4().hex}"
    cur.execute(
        """
        insert into message (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, raw)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (thread_id, channel, external_id, direction, sent_at, from_identity_id, "hi", psycopg.types.json.Json({})),
    )
    message_id = str(cur.fetchone()[0])
    for identity_id in participant_ids:
        role = "from" if identity_id == from_identity_id else "to"
        cur.execute(
            "insert into message_participant (message_id, identity_id, role) values (%s, %s, %s)",
            (message_id, identity_id, role),
        )
    return message_id


class TestReplySignal:
    def test_contact_with_message_history(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"contact-{uuid.uuid4().hex}@example.com")
        thread_id = _make_thread(cur, "outlook")

        now = datetime.now(UTC)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now - timedelta(days=2))
        _make_message(cur, thread_id, "outlook", "outbound", self_id, [self_id, contact_id], now - timedelta(days=1))

        result = reply_signal(cur, contact_id)

        assert result.sent_count == 1
        assert result.received_count == 1
        assert result.reciprocity_ratio == 1.0
        assert result.last_contact_at is not None

    def test_contact_with_no_message_history(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = str(uuid.uuid4())  # no identity/message rows at all for this id

        result = reply_signal(cur, contact_id)

        assert result.sent_count is None
        assert result.received_count is None
        assert result.reciprocity_ratio is None
        assert result.last_contact_at is None
