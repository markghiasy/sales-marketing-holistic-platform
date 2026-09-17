from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg

from adapters.inbox_query import get_detail, list_conversations, mark_read


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

    def test_unread_works_through_real_upsert_path(self, db_conn: psycopg.Connection):
        # Regression test: the unread subquery used to read
        # thread.last_message_at, a column nothing in the real ingest
        # path (adapters.store_writer.upsert()) ever writes — so unread
        # was always false against real data. This test goes through the
        # actual upsert() function (not the hand-rolled _make_message
        # helper above, and without ever touching thread.last_message_at)
        # to prove the query now derives unread correctly on real data.
        from adapters.envelope import Channel, Direction, Envelope
        from adapters.store_writer import upsert

        cur = db_conn.cursor()
        env = Envelope(
            channel=Channel.outlook,
            external_id=f"real-upsert-{uuid.uuid4().hex}",
            thread_external_id=f"real-upsert-thread-{uuid.uuid4().hex}",
            direction=Direction.inbound,
            sent_at=datetime.now(UTC),
            from_handle=f"real-{uuid.uuid4().hex}@example.com",
            to_handles=[f"me-{uuid.uuid4().hex}@example.com"],
            from_display_name="Real Upsert Contact",
            body_text="hello via real upsert",
        )
        identity_id = upsert(db_conn, env, self_handle=env.to_handles[0])

        rows = list_conversations(cur)

        row = next(r for r in rows if r.person_key == identity_id)
        assert row.unread is True

    def test_hides_stale_unknown_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "whatsapp", f"me-{uuid.uuid4().hex}", is_self=True)
        contact_id = _make_identity(cur, "whatsapp", f"c-{uuid.uuid4().hex}")  # no display_name
        old = datetime.now(UTC) - timedelta(days=400)
        thread_id = _make_thread(cur, "whatsapp", last_read_at=old)
        _make_message(cur, thread_id, "whatsapp", "inbound", contact_id, [contact_id, self_id], old)

        rows = list_conversations(cur)

        assert all(r.person_key != contact_id for r in rows)

    def test_hides_single_message_unknown_contact_even_if_recent(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "whatsapp", f"me-{uuid.uuid4().hex}", is_self=True)
        contact_id = _make_identity(cur, "whatsapp", f"c-{uuid.uuid4().hex}")  # no display_name
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "whatsapp", last_read_at=now)
        _make_message(cur, thread_id, "whatsapp", "inbound", contact_id, [contact_id, self_id], now)

        rows = list_conversations(cur)

        assert all(r.person_key != contact_id for r in rows)

    def test_keeps_stale_contact_with_a_known_name(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "whatsapp", f"me-{uuid.uuid4().hex}", is_self=True)
        contact_id = _make_identity(cur, "whatsapp", f"c-{uuid.uuid4().hex}", display_name="Old Friend")
        old = datetime.now(UTC) - timedelta(days=400)
        thread_id = _make_thread(cur, "whatsapp", last_read_at=old)
        _make_message(cur, thread_id, "whatsapp", "inbound", contact_id, [contact_id, self_id], old)

        rows = list_conversations(cur)

        assert any(r.person_key == contact_id for r in rows)

    def test_keeps_unknown_contact_with_multiple_recent_messages(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "whatsapp", f"me-{uuid.uuid4().hex}", is_self=True)
        contact_id = _make_identity(cur, "whatsapp", f"c-{uuid.uuid4().hex}")  # no display_name
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "whatsapp", last_read_at=now)
        _make_message(cur, thread_id, "whatsapp", "inbound", contact_id, [contact_id, self_id], now - timedelta(hours=1), body_text="hi")
        _make_message(cur, thread_id, "whatsapp", "inbound", contact_id, [contact_id, self_id], now, body_text="you there?")

        rows = list_conversations(cur)

        assert any(r.person_key == contact_id for r in rows)

    def test_hides_contact_whose_most_recent_message_is_automated(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Newsletter Bot")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        message_id = _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)
        cur.execute("update message set is_automated = true where id = %s", (message_id,))

        rows = list_conversations(cur)

        assert all(r.person_key != contact_id for r in rows)

    def test_keeps_contact_when_automated_message_is_not_the_most_recent(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Real Person")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        old_automated_id = _make_message(
            cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now - timedelta(hours=1)
        )
        cur.execute("update message set is_automated = true where id = %s", (old_automated_id,))
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now, body_text="real reply")

        rows = list_conversations(cur)

        assert any(r.person_key == contact_id for r in rows)


class TestGetDetail:
    def test_groups_messages_into_threads_ordered_by_first_message(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Priya")
        now = datetime.now(UTC)

        thread_b = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_b, "outlook", "inbound", contact_id, [contact_id, self_id], now - timedelta(days=9), body_text="pricing by phase")
        cur.execute("update message set subject = %s where thread_id = %s", ("Services agreement", thread_b))

        thread_a = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_a, "outlook", "inbound", contact_id, [contact_id, self_id], now - timedelta(days=14), body_text="kicking things off")
        cur.execute("update message set subject = %s where thread_id = %s", ("Q4 rollout", thread_a))

        detail = get_detail(cur, contact_id)

        assert detail is not None
        assert detail.name == "Priya"
        assert [g.subject for g in detail.threads] == ["Q4 rollout", "Services agreement"]
        assert detail.threads[0].messages[0].text == "kicking things off"
        assert detail.threads[0].messages[0].sender == "them"
        assert detail.threads[0].messages[0].from_name is None

    def test_third_party_message_carries_from_name(self, db_conn: psycopg.Connection):
        # Real bug found 2026-09-17: viewing Dr Sam Donegan's conversation,
        # a message actually sent by a cc'd third party (Barney) rendered
        # as an indistinguishable generic "them" bubble -- looked exactly
        # like a message from Sam, with nothing showing who really sent it.
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"sam-{uuid.uuid4().hex}@example.com", display_name="Dr Sam Donegan")
        third_party_id = _make_identity(cur, "outlook", f"barney-{uuid.uuid4().hex}@example.com", display_name="Barney Howells")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(
            cur, thread_id, "outlook", "inbound", third_party_id,
            [third_party_id, contact_id, self_id], now, body_text="Hope you're feeling better",
        )

        detail = get_detail(cur, contact_id)

        assert detail is not None
        msg = detail.threads[0].messages[0]
        assert msg.sender == "them"
        assert msg.from_name == "Barney Howells"

    def test_message_carries_to_and_cc_labels(self, db_conn: psycopg.Connection):
        # Real shape: an outbound email Eva sent to Martin, cc'ing Luisa
        # and a contact with no display_name (should fall back to handle).
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        martin_id = _make_identity(cur, "outlook", f"martin-{uuid.uuid4().hex}@example.com", display_name="Martin")
        luisa_id = _make_identity(cur, "outlook", f"luisa-{uuid.uuid4().hex}@example.com", display_name="Luisa")
        no_name_handle = f"noname-{uuid.uuid4().hex}@example.com"
        no_name_id = _make_identity(cur, "outlook", no_name_handle)
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        message_id = _make_message(cur, thread_id, "outlook", "outbound", self_id, [self_id, martin_id], now, body_text="hi")
        cur.execute(
            "insert into message_participant (message_id, identity_id, role) values (%s, %s, 'cc'), (%s, %s, 'cc')",
            (message_id, luisa_id, message_id, no_name_id),
        )

        detail = get_detail(cur, martin_id)

        msg = detail.threads[0].messages[0]
        assert msg.to == ["Martin"]
        assert set(msg.cc) == {"Luisa", no_name_handle}

    def test_no_subject_for_channels_without_one(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "whatsapp", "15555550001", is_self=True)
        contact_id = _make_identity(cur, "whatsapp", "15555550002", display_name="Marcus")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "whatsapp", last_read_at=now)
        _make_message(cur, thread_id, "whatsapp", "inbound", contact_id, [contact_id, self_id], now, body_text="hey")

        detail = get_detail(cur, contact_id)

        assert detail.threads[0].subject is None

    def test_no_ai_brief_row_returns_placeholder_context(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)

        detail = get_detail(cur, contact_id)

        assert detail.context == ["AI brief hasn't been generated for this contact yet — check back after the next sync."]
        assert detail.graph == {"org": None, "people": []}

    def test_unknown_person_key_returns_none(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        assert get_detail(cur, str(uuid.uuid4())) is None


class TestMarkRead:
    def test_marks_all_threads_for_person_read(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=None)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)

        mark_read(cur, contact_id)

        cur.execute("select last_read_at from thread where id = %s", (thread_id,))
        assert cur.fetchone()[0] is not None
