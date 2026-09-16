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
