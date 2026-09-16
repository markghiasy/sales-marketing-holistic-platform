# tests/test_ai_brief.py
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
import pytest

from adapters.ai_brief import (
    PROMPT_VERSION,
    generate_brief,
    person_keys_for_identities,
    refresh_touched,
    refresh_touched_best_effort,
)


def _make_identity(cur, channel: str, handle: str, is_self: bool = False, display_name: str | None = None) -> str:
    cur.execute(
        "insert into identity (channel, handle, is_self, display_name) values (%s, %s, %s, %s) returning id",
        (channel, handle, is_self, display_name),
    )
    return str(cur.fetchone()[0])


def _make_thread(cur, channel: str) -> str:
    external_id = f"thread-{uuid.uuid4().hex}"
    cur.execute("insert into thread (channel, external_id) values (%s, %s) returning id", (channel, external_id))
    return str(cur.fetchone()[0])


def _make_message(cur, thread_id, channel, direction, from_identity_id, participant_ids, sent_at, body_text):
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


@dataclass
class _FakeBlock:
    text: str


@dataclass
class _FakeResponse:
    content: list


class _FakeMessages:
    def __init__(self, response_json: dict):
        self._response_json = response_json
        self.last_call_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeResponse(content=[_FakeBlock(text=json.dumps(self._response_json))])


class _FakeClient:
    def __init__(self, response_json: dict):
        self.messages = _FakeMessages(response_json)


class TestGenerateBrief:
    def test_parses_response_and_upserts_ai_brief(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Priya")
        thread_id = _make_thread(cur, "outlook")
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], datetime.now(UTC), "need the agreement by friday")

        fake_client = _FakeClient({
            "summary": "Needs the agreement by Friday.",
            "context": ["Priya works at Brightstone Realty."],
            "topic": "Contract Request",
            "graph": {"org": {"name": "Brightstone Realty", "blurb": "Employer"}, "people": []},
            "urgency": 3,
        })

        brief = generate_brief(cur, contact_id, client=fake_client)

        assert brief.summary == "Needs the agreement by Friday."
        assert brief.topic == "Contract Request"
        assert brief.urgency == 3
        assert brief.prompt_version == PROMPT_VERSION
        assert fake_client.messages.last_call_kwargs["model"]  # a model string was passed

        cur.execute("select summary, topic, urgency from ai_brief where person_key = %s", (contact_id,))
        row = cur.fetchone()
        assert row == ("Needs the agreement by Friday.", "Contract Request", 3)

    def test_second_call_overwrites_the_row(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Priya")
        thread_id = _make_thread(cur, "outlook")
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], datetime.now(UTC), "first message")

        generate_brief(cur, contact_id, client=_FakeClient({
            "summary": "First summary.", "context": [], "topic": "General",
            "graph": {"org": None, "people": []}, "urgency": 1,
        }))
        generate_brief(cur, contact_id, client=_FakeClient({
            "summary": "Second summary.", "context": [], "topic": "General",
            "graph": {"org": None, "people": []}, "urgency": 2,
        }))

        cur.execute("select count(*), max(summary) from ai_brief where person_key = %s", (contact_id,))
        count, summary = cur.fetchone()
        assert count == 1
        assert summary == "Second summary."

    def test_malformed_json_response_raises(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test")
        thread_id = _make_thread(cur, "outlook")
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], datetime.now(UTC), "hi")

        class _BrokenMessages:
            def create(self, **kwargs):
                return _FakeResponse(content=[_FakeBlock(text="not json")])

        class _BrokenClient:
            messages = _BrokenMessages()

        try:
            generate_brief(cur, contact_id, client=_BrokenClient())
            raise AssertionError("expected an exception for malformed JSON")
        except (ValueError, json.JSONDecodeError):
            pass


class TestPersonKeysForIdentities:
    def test_maps_identity_ids_to_person_keys(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com")

        result = person_keys_for_identities(cur, {contact_id})

        assert result == {contact_id}  # no person_id set -> coalesces to the identity's own id

    def test_empty_input_returns_empty_set(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        assert person_keys_for_identities(cur, set()) == set()

    def test_excludes_self_identities(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com")

        result = person_keys_for_identities(cur, {self_id, contact_id})

        assert result == {contact_id}


class TestRefreshTouched:
    @pytest.fixture
    def _created_ids(self, db_conn):
        # refresh_touched() opens its OWN connection, separate from
        # db_conn — both tests below must db_conn.commit() their seed
        # rows so that other connection can see them, which means
        # db_conn's rollback-on-teardown can never clean them up (same
        # problem/pattern as tests/test_onboarding_app.py's
        # _created_identity_ids / _created fixtures). Without this,
        # every ai_brief/message/thread/identity row these tests commit
        # accumulates permanently in the local dev Postgres. Tests append
        # the ids they create; this fixture deletes them afterward.
        ids = {"identity_ids": [], "thread_ids": [], "message_ids": [], "person_keys": []}
        yield ids
        cur = db_conn.cursor()
        if ids["person_keys"]:
            cur.execute("delete from ai_brief where person_key = any(%s)", (ids["person_keys"],))
        if ids["message_ids"]:
            cur.execute("delete from message_participant where message_id = any(%s)", (ids["message_ids"],))
            cur.execute("delete from message where id = any(%s)", (ids["message_ids"],))
        if ids["thread_ids"]:
            cur.execute("delete from thread where id = any(%s)", (ids["thread_ids"],))
        if ids["identity_ids"]:
            cur.execute("delete from identity where id = any(%s)", (ids["identity_ids"],))
        db_conn.commit()

    def test_generates_a_brief_for_each_touched_person(self, db_conn: psycopg.Connection, monkeypatch, _created_ids):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test")
        thread_id = _make_thread(cur, "outlook")
        message_id = _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], datetime.now(UTC), "hi")
        _created_ids["identity_ids"] += [self_id, contact_id]
        _created_ids["thread_ids"].append(thread_id)
        _created_ids["message_ids"].append(message_id)
        _created_ids["person_keys"].append(contact_id)
        db_conn.commit()  # refresh_touched opens its OWN connection — this test's rows must be visible to it

        fake_client = _FakeClient({
            "summary": "s", "context": [], "topic": "General", "graph": {"org": None, "people": []}, "urgency": 1,
        })
        monkeypatch.setenv("DATABASE_URL", "postgresql://comms:comms@localhost:5432/comms")

        refresh_touched({contact_id}, client=fake_client)

        cur2 = db_conn.cursor()
        cur2.execute("select summary from ai_brief where person_key = %s", (contact_id,))
        assert cur2.fetchone()[0] == "s"

    def test_one_bad_person_does_not_block_the_rest(self, db_conn: psycopg.Connection, monkeypatch, _created_ids):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        good_id = _make_identity(cur, "outlook", f"good-{uuid.uuid4().hex}@example.com", display_name="Good")
        thread_id = _make_thread(cur, "outlook")
        message_id = _make_message(cur, thread_id, "outlook", "inbound", good_id, [good_id, self_id], datetime.now(UTC), "hi")
        _created_ids["identity_ids"] += [self_id, good_id]
        _created_ids["thread_ids"].append(thread_id)
        _created_ids["message_ids"].append(message_id)
        _created_ids["person_keys"].append(good_id)
        db_conn.commit()
        monkeypatch.setenv("DATABASE_URL", "postgresql://comms:comms@localhost:5432/comms")

        class _BrokenMessages:
            def create(self, **kwargs):
                return _FakeResponse(content=[_FakeBlock(text="not json")])

        class _BrokenClient:
            messages = _BrokenMessages()

        nonexistent_id = str(uuid.uuid4())  # generate_brief will find no messages/facts, but the LLM call still happens
        refresh_touched({nonexistent_id, good_id}, client=_BrokenClient())  # _BrokenClient always returns malformed JSON

        # both fail with _BrokenClient, but the call must not raise —
        # rerun with a working client and confirm the good one now succeeds
        refresh_touched({good_id}, client=_FakeClient({
            "summary": "recovered", "context": [], "topic": "General", "graph": {"org": None, "people": []}, "urgency": 1,
        }))
        cur2 = db_conn.cursor()
        cur2.execute("select summary from ai_brief where person_key = %s", (good_id,))
        assert cur2.fetchone()[0] == "recovered"

    def test_refresh_touched_best_effort_never_raises(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://nonexistent-host-for-this-test:5432/comms")
        refresh_touched_best_effort({str(uuid.uuid4())})  # DB unreachable -> caught, not raised
