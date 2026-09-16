"""LLM precompute for the triage inbox (Block C, STU-131): one call per
touched contact per sync, cached in ai_brief — never called live from a
page request. See
docs/superpowers/specs/2026-09-16-triage-inbox-real-data-llm-design.md.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

import psycopg
from dotenv import load_dotenv

from .reply_signal import reply_signal

PROMPT_VERSION = "v1"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


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
    return anthropic.Anthropic()


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

Full message history across every channel (Outlook/WhatsApp/LinkedIn),
oldest first: {json.dumps(data["messages"])}

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{
  "summary": "one short third-person sentence describing what this contact needs or wants right now",
  "context": ["a full first-person-voice sentence of background", "..."],
  "topic": "a short 1-3 word topic phrase for this contact's current thread",
  "graph": {{
    "org": {{"name": "...", "blurb": "..."}} or null if no employer is known,
    "people": [{{"name": "...", "relation": "a short phrase, only if the messages or facts actually support it"}}]
  }},
  "urgency": 1, 2, or 3 (3 = needs action soon)
}}
"""


def generate_brief(cur, person_key: str, client=None) -> AiBrief:
    client = client or _default_client()
    data = _gather_input(cur, person_key)
    model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": _build_prompt(data)}],
    )
    text = response.content[0].text
    parsed = json.loads(text)  # raises json.JSONDecodeError on malformed output — caller decides how to handle it

    brief = AiBrief(
        person_key=person_key,
        summary=parsed["summary"],
        context=parsed["context"],
        topic=parsed["topic"],
        graph=parsed["graph"],
        urgency=parsed["urgency"],
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
    return brief
