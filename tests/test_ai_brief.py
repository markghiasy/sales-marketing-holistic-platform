# tests/test_ai_brief.py
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

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
class _FakeToolUseBlock:
    input: dict
    type: str = "tool_use"
    name: str = "submit_brief"


@dataclass
class _FakeResponse:
    content: list
    stop_reason: str = "tool_use"


class _FakeMessages:
    """Simulates Anthropic's tool-use response shape: a forced tool_choice
    means the real API always returns a tool_use block whose .input is
    already a parsed dict matching the tool's input_schema — never text
    that needs json.loads()."""

    def __init__(self, response_json: dict):
        self._response_json = response_json
        self.last_call_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeResponse(content=[_FakeToolUseBlock(input=self._response_json)])

    def count_tokens(self, **kwargs):
        return SimpleNamespace(input_tokens=100)


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

    def test_malformed_tool_input_raises(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Test")
        thread_id = _make_thread(cur, "outlook")
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], datetime.now(UTC), "hi")

        class _BrokenMessages:
            def count_tokens(self, **kwargs):
                return SimpleNamespace(input_tokens=100)

            def create(self, **kwargs):
                # missing every required field — pydantic.ValidationError
                # (a ValueError subclass) on model_validate()
                return _FakeResponse(content=[_FakeToolUseBlock(input={})])

        class _BrokenClient:
            messages = _BrokenMessages()

        try:
            generate_brief(cur, contact_id, client=_BrokenClient())
            raise AssertionError("expected an exception for malformed tool input")
        except ValueError:
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

        class _BrokenMessages:
            def count_tokens(self, **kwargs):
                return SimpleNamespace(input_tokens=100)

            def create(self, **kwargs):
                return _FakeResponse(content=[_FakeToolUseBlock(input={})])

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

    def test_refresh_failure_that_cannot_be_recorded_is_sanitized_and_raised(self, monkeypatch, capsys):
        def unavailable(*args, **kwargs):
            raise RuntimeError("secret connection string and message contents")

        monkeypatch.setattr("adapters.ai_brief.refresh_touched", unavailable)
        with pytest.raises(RuntimeError, match="AI brief refresh status could not be recorded") as exc:
            refresh_touched_best_effort({str(uuid.uuid4())})
        assert "secret" not in str(exc.value)
        assert "secret" not in capsys.readouterr().err

    def test_failure_is_committed_preserves_cache_and_later_success_clears_status(self, db_conn, monkeypatch):
        def no_implicit_env_read():
            raise AssertionError("Explicit database configuration must not load .env")

        monkeypatch.setattr("adapters.ai_brief.load_dotenv", no_implicit_env_read)
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Synthetic")
        db_conn.commit()
        refresh_touched({contact_id}, client=SimpleNamespace(messages=_BudgetMessages()))
        refresh_touched({contact_id}, client=SimpleNamespace(messages=_BudgetMessages(create_error=True)))
        cur.execute("select status, error_code from ai_brief_status where person_key = %s", (contact_id,))
        assert cur.fetchone() == ("failed", "provider_failed")
        cur.execute("select summary from ai_brief where person_key = %s", (contact_id,))
        assert cur.fetchone() == ("Needs a reply.",)
        refresh_touched({contact_id}, client=SimpleNamespace(messages=_BudgetMessages()))
        cur.execute("select status, error_code from ai_brief_status where person_key = %s", (contact_id,))
        assert cur.fetchone() == ("success", None)


class _RecordingCursor:
    def __init__(self):
        self.writes = []

    def execute(self, sql, params):
        self.writes.append((sql, params))

    @property
    def status(self):
        return next(params for sql, params in reversed(self.writes) if "ai_brief_status" in sql)


class _BudgetMessages(_FakeMessages):
    def __init__(self, counts=(100,), response=None, count_error=False, create_error=False):
        super().__init__(response if response is not None else {
            "summary": "Needs a reply.", "context": [], "topic": "Reply",
            "graph": {"org": None, "people": []}, "urgency": 2,
        })
        self.counts = list(counts)
        self.count_calls = []
        self.count_error = count_error
        self.create_error = create_error

    def count_tokens(self, **kwargs):
        self.count_calls.append(kwargs)
        if self.count_error:
            raise RuntimeError("sensitive original email in provider error")
        return SimpleNamespace(input_tokens=self.counts.pop(0) if len(self.counts) > 1 else self.counts[0])

    def create(self, **kwargs):
        if self.create_error:
            raise RuntimeError("sensitive original email in provider error")
        return super().create(**kwargs)


class TestBudgetedBrief:
    @pytest.fixture
    def synthetic_input(self, monkeypatch):
        # No database, credentials, or real message payloads in these provider-contract tests.
        data = {"name": "Synthetic", "facts": [], "reply_signal": {}, "messages": [
            {"text": "old synthetic history " * 100, "sent_at": "2020-01-01", "channel": "outlook", "direction": "inbound"},
            {"text": "new synthetic request", "sent_at": "2026-09-28", "channel": "outlook", "direction": "inbound"},
        ]}
        monkeypatch.setattr("adapters.ai_brief._gather_input", lambda *_: data)
        return data

    def test_actual_request_is_strict_and_counted_before_generation(self, synthetic_input):
        cur, provider = _RecordingCursor(), _BudgetMessages()
        generate_brief(cur, "synthetic-person", client=SimpleNamespace(messages=provider))
        request = provider.last_call_kwargs
        tool = request["tools"][0]
        assert tool["strict"] is True
        schema = tool["input_schema"]
        assert schema["additionalProperties"] is False
        assert "graph" in schema["required"]
        assert schema["properties"]["urgency"]["enum"] == [1, 2, 3]
        for obj in schema["$defs"].values():
            assert obj["additionalProperties"] is False
        assert provider.count_calls == [{k: v for k, v in request.items() if k != "max_tokens"}]
        assert cur.status[1] == "success"

    def test_over_budget_keeps_recent_history_and_records_truncation(self, synthetic_input):
        cur, provider = _RecordingCursor(), _BudgetMessages(counts=(207373, 100))
        generate_brief(cur, "synthetic-person", client=SimpleNamespace(messages=provider))
        prompt = provider.last_call_kwargs["messages"][0]["content"]
        assert "new synthetic request" in prompt
        assert "old synthetic history" not in prompt
        assert "partial" in prompt.lower()
        assert len(provider.count_calls) == 2
        assert cur.status[1] == "truncated"
        assert cur.status[4:7] == (100, 207373, 1)
        assert len(synthetic_input["messages"]) == 2  # caller's input remains intact

    def test_unshrinkable_request_is_skipped_without_generation(self, synthetic_input):
        cur, provider = _RecordingCursor(), _BudgetMessages(counts=(207373,))
        result = generate_brief(cur, "synthetic-person", client=SimpleNamespace(messages=provider))
        assert result is None
        assert provider.last_call_kwargs is None
        assert 1 < len(provider.count_calls) <= 10
        assert cur.status[1:3] == ("skipped", "input_budget_exceeded")

    @pytest.mark.parametrize("failure,code", [("count", "token_count_failed"), ("create", "provider_failed"), ("invalid", "invalid_response")])
    def test_provider_failures_are_persisted_and_sanitized(self, synthetic_input, failure, code):
        cur = _RecordingCursor()
        provider = _BudgetMessages(count_error=failure == "count", create_error=failure == "create", response={} if failure == "invalid" else None)
        with pytest.raises(ValueError) as exc:
            generate_brief(cur, "synthetic-person", client=SimpleNamespace(messages=provider))
        assert "sensitive" not in str(exc.value)
        assert cur.status[1:3] == ("failed", code)
        assert "sensitive" not in repr(cur.writes)
        if failure == "count":
            assert provider.last_call_kwargs is None

    def test_one_large_body_is_shortened_and_recounted(self, synthetic_input):
        synthetic_input["messages"] = [{"text": "synthetic " * 1000}]
        cur, provider = _RecordingCursor(), _BudgetMessages(counts=(207373, 100))
        generate_brief(cur, "synthetic-person", client=SimpleNamespace(messages=provider))
        assert len(provider.count_calls[1]["messages"][0]["content"]) < len(provider.count_calls[0]["messages"][0]["content"])
        assert cur.status[1] == "truncated"
        assert cur.status[6:8] == (0, True)
        assert len(synthetic_input["messages"][0]["text"]) == 10000

    def test_exact_input_budget_is_allowed(self, synthetic_input, monkeypatch):
        monkeypatch.setattr("adapters.ai_brief._MAX_INPUT_TOKENS", 100)
        cur, provider = _RecordingCursor(), _BudgetMessages(counts=(100,))
        assert generate_brief(cur, "synthetic-person", client=SimpleNamespace(messages=provider)) is not None
        assert len(provider.count_calls) == 1
        assert cur.status[1] == "success"

    def test_truncated_generation_is_not_cached_even_if_fields_parse(self, synthetic_input):
        class Incomplete(_BudgetMessages):
            def create(self, **kwargs):
                response = super().create(**kwargs)
                response.stop_reason = "max_tokens"
                return response

        cur = _RecordingCursor()
        with pytest.raises(ValueError, match="invalid_response"):
            generate_brief(cur, "synthetic-person", client=SimpleNamespace(messages=Incomplete()))
        assert cur.status[1:3] == ("failed", "invalid_response")
        assert all("insert into ai_brief (" not in sql for sql, _ in cur.writes)

    def test_real_sdk_serializes_strict_tool_on_count_and_generation(self, synthetic_input):
        import anthropic
        import httpx

        requests = []
        payload = {"summary": "Synthetic brief", "context": [], "topic": "Reply",
                   "graph": {"org": None, "people": []}, "urgency": 2}

        def handler(request):
            body = json.loads(request.content)
            requests.append((request.url.path, body))
            if request.url.path.endswith("count_tokens"):
                return httpx.Response(200, json={"input_tokens": 100})
            return httpx.Response(200, json={
                "id": "msg_synthetic", "type": "message", "role": "assistant",
                "model": body["model"], "content": [{"type": "tool_use", "id": "tool_synthetic",
                    "name": "submit_brief", "input": payload}],
                "stop_reason": "tool_use", "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 30},
            })

        # MockTransport intercepts every request; no network or real credentials.
        with anthropic.Anthropic(api_key="synthetic-test-key", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
            result = generate_brief(_RecordingCursor(), "synthetic-person", client=client)
        assert result.summary == "Synthetic brief"
        assert [path for path, _ in requests] == ["/v1/messages/count_tokens", "/v1/messages"]
        counted, generated = [body for _, body in requests]
        assert counted == {k: v for k, v in generated.items() if k != "max_tokens"}
        assert generated["tools"][0]["strict"] is True
