# tests/test_ai_brief.py
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from adapters.ai_brief import PROMPT_VERSION, generate_brief


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
