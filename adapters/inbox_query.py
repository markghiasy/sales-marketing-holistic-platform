"""Real data for the triage inbox (Block C, STU-131) — replaces
/inbox's MOCK_CONVERSATIONS. See
docs/superpowers/specs/2026-09-16-triage-inbox-real-data-llm-design.md.

Reuses contact_stats/contact_last_message (db/migrations/0002_graph_views.sql)
rather than re-deriving their identity/message_participant joins here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConversationRow:
    person_key: str
    name: str
    channel: str
    last_message_at: str  # ISO 8601
    unread: bool
    unanswered: bool
    summary: str
    topic: str
    urgency: int
    has_draft: bool


_DEFAULT_TOPIC = "General"
_DEFAULT_URGENCY = 2


def list_conversations(cur) -> list[ConversationRow]:
    cur.execute(
        """
        select
            cs.contact_key,
            cs.display_name,
            clm.channel,
            clm.sent_at,
            clm.direction,
            clm.snippet,
            ab.summary,
            ab.topic,
            ab.urgency,
            coalesce(unread.is_unread, false) as is_unread
        from contact_stats cs
        join contact_last_message clm on clm.contact_key = cs.contact_key
        left join ai_brief ab on ab.person_key = cs.contact_key
        left join (
            select
                coalesce(i.person_id, i.id) as contact_key,
                bool_or(t.last_message_at > coalesce(t.last_read_at, '-infinity'::timestamptz)) as is_unread
            from identity i
            join message_participant mp on mp.identity_id = i.id
            join message m on m.id = mp.message_id
            join thread t on t.id = m.thread_id
            where i.is_self = false
            group by coalesce(i.person_id, i.id)
        ) unread on unread.contact_key = cs.contact_key
        order by clm.sent_at desc
        """
    )
    rows = []
    for r in cur.fetchall():
        (contact_key, display_name, channel, sent_at, direction, snippet,
         ai_summary, ai_topic, ai_urgency, is_unread) = r
        rows.append(ConversationRow(
            person_key=str(contact_key),
            name=display_name or "(unknown)",
            channel=channel,
            last_message_at=sent_at.isoformat(),
            unread=bool(is_unread),
            unanswered=(direction == "inbound"),
            summary=ai_summary if ai_summary is not None else snippet,
            topic=ai_topic if ai_topic is not None else _DEFAULT_TOPIC,
            urgency=ai_urgency if ai_urgency is not None else _DEFAULT_URGENCY,
            has_draft=False,  # no real draft generation this pass
        ))
    return rows


_PLACEHOLDER_CONTEXT = ["AI brief hasn't been generated for this contact yet — check back after the next sync."]
_PLACEHOLDER_GRAPH = {"org": None, "people": []}


@dataclass
class ThreadMessage:
    sender: str  # "you" | "them"
    text: str
    sent_at: str


@dataclass
class ThreadGroup:
    channel: str
    subject: str | None
    messages: list[ThreadMessage]


@dataclass
class ConversationDetail:
    person_key: str
    name: str
    channel: str
    last_message_at: str
    threads: list[ThreadGroup]
    context: list[str]
    graph: dict
    topic: str
    urgency: int


def _identity_ids_for_person(cur, person_key: str) -> list[str]:
    cur.execute(
        "select id from identity where coalesce(person_id, id) = %s",
        (person_key,),
    )
    return [str(row[0]) for row in cur.fetchall()]


def get_detail(cur, person_key: str) -> ConversationDetail | None:
    identity_ids = _identity_ids_for_person(cur, person_key)
    if not identity_ids:
        return None

    cur.execute(
        """
        select t.id, t.channel, m.subject, m.direction, m.body_text, m.sent_at
        from message m
        join thread t on t.id = m.thread_id
        where m.id in (
            select mp.message_id from message_participant mp
            where mp.identity_id = any(%s)
        )
        order by m.sent_at
        """,
        (identity_ids,),
    )
    rows = cur.fetchall()
    if not rows:
        return None

    groups_by_thread: dict[str, dict] = {}
    for thread_id, channel, subject, direction, body_text, sent_at in rows:
        thread_id = str(thread_id)
        group = groups_by_thread.setdefault(
            thread_id, {"channel": channel, "subject": None, "messages": [], "first_sent_at": sent_at}
        )
        if subject and group["subject"] is None:
            group["subject"] = subject
        group["messages"].append(ThreadMessage(
            sender="you" if direction == "outbound" else "them",
            text=body_text,
            sent_at=sent_at.isoformat(),
        ))

    ordered_groups = sorted(groups_by_thread.values(), key=lambda g: g["first_sent_at"])
    threads = [ThreadGroup(channel=g["channel"], subject=g["subject"], messages=g["messages"]) for g in ordered_groups]

    cur.execute("select max(display_name) from identity where id = any(%s)", (identity_ids,))
    name = cur.fetchone()[0] or "(unknown)"

    cur.execute(
        "select summary, context, topic, graph, urgency from ai_brief where person_key = %s",
        (person_key,),
    )
    brief_row = cur.fetchone()
    if brief_row:
        _summary, context, topic, graph, urgency = brief_row
    else:
        context, topic, graph, urgency = _PLACEHOLDER_CONTEXT, _DEFAULT_TOPIC, _PLACEHOLDER_GRAPH, _DEFAULT_URGENCY

    last_message = max(rows, key=lambda r: r[5])
    return ConversationDetail(
        person_key=person_key,
        name=name,
        channel=last_message[1],
        last_message_at=last_message[5].isoformat(),
        threads=threads,
        context=context,
        graph=graph,
        topic=topic,
        urgency=urgency,
    )


def mark_read(cur, person_key: str) -> None:
    identity_ids = _identity_ids_for_person(cur, person_key)
    if not identity_ids:
        return
    cur.execute(
        """
        update thread set last_read_at = now()
        where id in (
            select distinct t.id from thread t
            join message m on m.thread_id = t.id
            join message_participant mp on mp.message_id = m.id
            where mp.identity_id = any(%s)
        )
        """,
        (identity_ids,),
    )
