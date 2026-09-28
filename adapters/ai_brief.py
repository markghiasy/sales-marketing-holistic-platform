"""LLM precompute for the triage inbox (Block C, STU-131): one call per
touched contact per sync, cached in ai_brief — never called live from a
page request. See
docs/superpowers/specs/2026-09-16-triage-inbox-real-data-llm-design.md.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal

import psycopg
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from .reply_signal import reply_signal

PROMPT_VERSION = "v3"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_TOOL_NAME = "submit_brief"
_MAX_INPUT_TOKENS = 160_000  # leave headroom for output/provider counting differences
_MAX_PREFLIGHT_CALLS = 10


# Forced tool_choice selects the tool; strict:true enforces its schema.
# Closed objects and enum constraints are supported by strict tool use.
class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _OrgInfo(_StrictModel):
    name: str
    blurb: str


class _PersonRelation(_StrictModel):
    name: str
    relation: str


class _GraphInfo(_StrictModel):
    org: _OrgInfo | None
    people: list[_PersonRelation]


class _BriefResponse(_StrictModel):
    summary: str
    context: list[str]
    topic: str
    graph: _GraphInfo
    urgency: Literal[1, 2, 3]


@dataclass
class AiBrief:
    person_key: str
    summary: str
    context: list[str]
    topic: str
    graph: dict
    urgency: int
    model: str
    prompt_version: str


def _default_client():
    import anthropic
    return anthropic.Anthropic(timeout=45, max_retries=1)


def _gather_input(cur, person_key: str) -> dict:
    cur.execute("select max(display_name) from identity where coalesce(person_id, id) = %s", (person_key,))
    name = cur.fetchone()[0] or "(unknown)"

    cur.execute(
        """
        select m.channel, m.direction, m.body_text, m.sent_at
        from message m
        join message_participant mp on mp.message_id = m.id
        join identity i on i.id = mp.identity_id
        where coalesce(i.person_id, i.id) = %s
        order by m.sent_at
        """,
        (person_key,),
    )
    messages = [
        {"channel": r[0], "direction": r[1], "text": r[2], "sent_at": r[3].isoformat()}
        for r in cur.fetchall()
    ]

    cur.execute(
        """
        select f.fact_type, f.object_text, o.canonical_name
        from fact f
        join identity i on i.id = f.subject_identity_id
        left join organization o on o.id = f.object_org_id
        where coalesce(i.person_id, i.id) = %s and f.status != 'rejected'
        """,
        (person_key,),
    )
    facts = [{"fact_type": r[0], "object_text": r[1], "org_name": r[2]} for r in cur.fetchall()]

    signal = reply_signal(cur, person_key)

    return {
        "name": name,
        "messages": messages,
        "facts": facts,
        "reply_signal": {
            "sent_count": signal.sent_count,
            "received_count": signal.received_count,
            "reciprocity_ratio": signal.reciprocity_ratio,
            "last_contact_at": signal.last_contact_at.isoformat() if signal.last_contact_at else None,
        },
    }


def _build_prompt(data: dict) -> str:
    return f"""You are summarizing one contact's real message history for a busy
person triaging their inbox. All input below is real — do not invent any
fact, relationship, or organization you cannot point to in the messages
or the structured facts given.

Contact name: {data["name"]}

Structured facts (from identity resolution): {json.dumps(data["facts"])}

Reply signal (this person's own history with this contact): {json.dumps(data["reply_signal"])}

Message history across channels (Outlook/WhatsApp/LinkedIn),
oldest first: {json.dumps(data["messages"])}
Coverage: {"PARTIAL history: older messages or message text were omitted to fit the input budget. Do not claim complete history." if data.get("partial_history") else "Full available history."}

Call {_TOOL_NAME} with your summary. "summary" is one short third-person
sentence describing what this contact needs or wants right now. "context"
is a LIST of SEPARATE full first-person-voice sentences of background —
each list item is its own single fact, one sentence long. Never merge
multiple facts into one run-on sentence or collapse the list down to a
single item unless there is genuinely only one fact to report. "topic" is
a short 1-3 word phrase for this contact's current thread. "graph.org" is
this contact's employer if known, else null. "graph.people" is only
people the messages or facts actually support a relation for. "urgency"
is 1, 2, or 3 (3 = needs action soon).

Weight recency heavily when deciding WHICH facts to keep: the most recent
messages describe the contact's CURRENT state and should dominate
"summary", "topic", and "urgency". Older facts are background only —
keep a "context" item for one solely where it still explains something
about the current state (an open ask, a relationship, a commitment); drop
an old fact entirely once later messages have resolved or superseded it.
Each surviving fact still gets its own separate sentence in the list.
"""


_TOOL_SCHEMA = {
    "name": _TOOL_NAME,
    "strict": True,
    "description": "Submit the structured brief for this contact.",
    "input_schema": _BriefResponse.model_json_schema(),
}


class BriefGenerationError(ValueError):
    """Sanitized failure whose status has been written in the caller's transaction."""


def _record_status(cur, person_key, status, error_code, model, input_tokens=None,
                   original_input_tokens=None, omitted_messages=0, truncated_text=False):
    cur.execute(
        """
        insert into ai_brief_status
            (person_key, status, error_code, model, input_tokens, original_input_tokens,
             omitted_messages, truncated_text, attempted_at)
        values (%s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict (person_key) do update set
            status = excluded.status, error_code = excluded.error_code, model = excluded.model,
            input_tokens = excluded.input_tokens, original_input_tokens = excluded.original_input_tokens,
            omitted_messages = excluded.omitted_messages, truncated_text = excluded.truncated_text,
            attempted_at = excluded.attempted_at
        """,
        (person_key, status, error_code, model, input_tokens, original_input_tokens,
         omitted_messages, truncated_text),
    )


def generate_brief(cur, person_key: str, client=None) -> AiBrief | None:
    """Generate within a counted budget; caller commits the brief and latest status.

    Skips return None. Provider/validation failures write status then raise a
    sanitized BriefGenerationError; callers must commit that status (not rollback).
    Never overwrite the last successful brief on a failed or skipped attempt.
    """
    data = _gather_input(cur, person_key)
    model = os.environ.get("ANTHROPIC_MODEL") or _DEFAULT_MODEL
    data = {**data, "messages": [dict(m) for m in data["messages"]]}
    original_count = len(data["messages"])
    original_tokens = input_tokens = None
    truncated_text = False
    error_code = "provider_failed"
    try:
        client = client or _default_client()
        error_code = "token_count_failed"
        for attempt in range(_MAX_PREFLIGHT_CALLS):
            request = {
                "model": model, "tools": [_TOOL_SCHEMA],
                "tool_choice": {"type": "tool", "name": _TOOL_NAME},
                "messages": [{"role": "user", "content": _build_prompt(data)}],
            }
            # Count the exact serialized prompt AND tools, never chars/token guesses.
            input_tokens = client.messages.count_tokens(**request).input_tokens
            if not isinstance(input_tokens, int) or input_tokens < 0:
                raise ValueError("Invalid token count")
            if original_tokens is None:
                original_tokens = input_tokens
            if input_tokens <= _MAX_INPUT_TOKENS:
                break
            if attempt == _MAX_PREFLIGHT_CALLS - 1:
                break
            if len(data["messages"]) > 1:
                data["messages"] = data["messages"][len(data["messages"]) // 2:]
            elif data["messages"] and len(data["messages"][0].get("text") or "") > 32:
                text = data["messages"][0]["text"]
                data["messages"][0]["text"] = text[:len(text) // 2]
                truncated_text = True
            else:
                break  # irreducible facts/prompt: explicit skip, no generation call
            data["partial_history"] = True

        omitted = original_count - len(data["messages"])
        if input_tokens > _MAX_INPUT_TOKENS:
            _record_status(cur, person_key, "skipped", "input_budget_exceeded", model,
                           input_tokens, original_tokens, omitted, truncated_text)
            return None
        error_code = "provider_failed"
        response = client.messages.create(max_tokens=1024, **request)
        error_code = "invalid_response"
        if response.stop_reason != "tool_use":
            raise ValueError("Incomplete brief response")
        blocks = [b for b in response.content if b.type == "tool_use" and b.name == _TOOL_NAME]
        if len(blocks) != 1:
            raise ValueError("Missing brief tool")
        parsed = _BriefResponse.model_validate(blocks[0].input)
    except Exception:  # noqa: BLE001 — sanitize any provider/validation failure before persistence
        # Provider errors/validation errors can contain source text or credentials.
        # Only fixed error codes cross the persistence/logging boundary.
        _record_status(cur, person_key, "failed", error_code, model, input_tokens,
                       original_tokens, original_count - len(data["messages"]), truncated_text)
        raise BriefGenerationError(f"AI brief failed: {error_code}") from None

    brief = AiBrief(
        person_key=person_key,
        summary=parsed.summary,
        context=parsed.context,
        topic=parsed.topic,
        graph=parsed.graph.model_dump(),
        urgency=parsed.urgency,
        model=model,
        prompt_version=PROMPT_VERSION,
    )

    cur.execute(
        """
        insert into ai_brief (person_key, summary, context, topic, graph, urgency, model, prompt_version, generated_at)
        values (%s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict (person_key) do update set
            summary = excluded.summary, context = excluded.context, topic = excluded.topic,
            graph = excluded.graph, urgency = excluded.urgency, model = excluded.model,
            prompt_version = excluded.prompt_version, generated_at = excluded.generated_at
        """,
        (
            brief.person_key, brief.summary, psycopg.types.json.Json(brief.context), brief.topic,
            psycopg.types.json.Json(brief.graph), brief.urgency, brief.model, brief.prompt_version,
        ),
    )
    _record_status(cur, person_key, "truncated" if data.get("partial_history") else "success",
                   None, model, input_tokens, original_tokens, omitted, truncated_text)
    return brief


def person_keys_for_identities(cur, identity_ids: set[str]) -> set[str]:
    if not identity_ids:
        return set()
    cur.execute(
        "select coalesce(person_id, id) from identity where id = any(%s) and is_self = false",
        (list(identity_ids),),
    )
    return {str(row[0]) for row in cur.fetchall()}


def refresh_touched(person_keys: set[str], client=None) -> None:
    if not person_keys:
        return
    if not os.environ.get("DATABASE_URL"):
        load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for person_key in person_keys:
            try:
                generate_brief(cur, person_key, client=client)
                conn.commit()
            except BriefGenerationError:
                conn.commit()  # persist the sanitized failure written by generate_brief
            except Exception:  # noqa: BLE001 — isolate any per-contact storage failure
                conn.rollback()
                _record_status(cur, person_key, "failed", "storage_failed",
                               os.environ.get("ANTHROPIC_MODEL") or _DEFAULT_MODEL)
                conn.commit()


def refresh_touched_best_effort(person_keys: set[str], client=None) -> None:
    """Continue on recorded per-contact failures; never silently lose status.

    Historical name retained for sync callers. If storage is unavailable, no
    durable status is possible: raise a sanitized operational error instead.
    """
    try:
        refresh_touched(person_keys, client=client)
    except Exception:  # noqa: BLE001 — never expose connection details in a sync failure
        raise RuntimeError("AI brief refresh status could not be recorded; message sync data was retained.") from None
