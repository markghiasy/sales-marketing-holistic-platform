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
    # Eva's call 2026-09-17: contacts with no name AND (stale — no message
    # in over a year — OR only ever a single message) clutter the list
    # without adding much — mostly old WhatsApp chats where the platform's
    # own history sync only ever gave us one message, or long-dead
    # one-off senders. Hidden here, not deleted — the underlying rows are
    # untouched, so nothing is lost, this is purely a list-view filter.
    cur.execute(
        """
        select
            cs.contact_key,
            cs.display_name,
            clm.channel,
            clm.sent_at,
            clm.direction,
            clm.snippet,
            clm.is_automated,
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
                bool_or(m.sent_at > coalesce(t.last_read_at, '-infinity'::timestamptz)) as is_unread
            from identity i
            join message_participant mp on mp.identity_id = i.id
            join message m on m.id = mp.message_id
            join thread t on t.id = m.thread_id
            where i.is_self = false and m.direction = 'inbound'
            group by coalesce(i.person_id, i.id)
        ) unread on unread.contact_key = cs.contact_key
        where not (
            cs.display_name is null
            and (clm.sent_at < now() - interval '1 year' or cs.total_count = 1)
        )
        and not coalesce(clm.is_automated, false)
        order by clm.sent_at desc
        """
    )
    rows = []
    for r in cur.fetchall():
        (contact_key, display_name, channel, sent_at, direction, snippet,
         _is_automated, ai_summary, ai_topic, ai_urgency, is_unread) = r
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
    to: list[str]  # display name (falling back to handle) per To recipient —
                    # Outlook only, always [] for WhatsApp/LinkedIn
    cc: list[str]  # same, for Cc
    from_name: str | None  # set only when sender="them" AND the actual
                            # sender isn't this conversation's own contact —
                            # e.g. a cc'd third party replying in a group
                            # email thread. Real bug found 2026-09-17: every
                            # inbound message rendered as a generic "them"
                            # bubble with no indication of who actually sent
                            # it, so a reply from someone other than the
                            # contact you're viewing looked identical to one
                            # from the contact themselves.


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
        select m.id, t.id, t.channel, m.subject, m.direction, m.body_text, m.sent_at,
               m.from_identity_id, coalesce(fi.display_name, fi.handle)
        from message m
        join thread t on t.id = m.thread_id
        left join identity fi on fi.id = m.from_identity_id
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

    message_ids = [str(r[0]) for r in rows]
    cur.execute(
        """
        select mp.message_id, mp.role, coalesce(i.display_name, i.handle)
        from message_participant mp
        join identity i on i.id = mp.identity_id
        where mp.message_id = any(%s) and mp.role in ('to', 'cc')
        """,
        (message_ids,),
    )
    to_cc_by_message: dict[str, dict[str, list[str]]] = {}
    for message_id, role, label in cur.fetchall():
        entry = to_cc_by_message.setdefault(str(message_id), {"to": [], "cc": []})
        entry[role].append(label)

    identity_id_set = set(identity_ids)
    groups_by_thread: dict[str, dict] = {}
    for message_id, thread_id, channel, subject, direction, body_text, sent_at, from_identity_id, from_label in rows:
        message_id = str(message_id)
        thread_id = str(thread_id)
        group = groups_by_thread.setdefault(
            thread_id, {"channel": channel, "subject": None, "messages": [], "first_sent_at": sent_at}
        )
        if subject and group["subject"] is None:
            group["subject"] = subject
        if not body_text or not body_text.strip():
            # Real case found 2026-09-17: a bare forward with no comment
            # added above it has nothing left once the quote/forward chain
            # is correctly cut -- not a stripping bug, the new content
            # really is empty. Renders as an empty bubble with nothing to
            # read, so it's dropped here rather than shown blank.
            continue
        to_cc = to_cc_by_message.get(message_id, {"to": [], "cc": []})
        sender = "you" if direction == "outbound" else "them"
        is_third_party = sender == "them" and str(from_identity_id) not in identity_id_set
        group["messages"].append(ThreadMessage(
            sender=sender,
            text=body_text,
            sent_at=sent_at.isoformat(),
            to=to_cc["to"],
            cc=to_cc["cc"],
            from_name=from_label if is_third_party else None,
        ))

    ordered_groups = sorted(groups_by_thread.values(), key=lambda g: g["first_sent_at"])
    threads = [
        ThreadGroup(channel=g["channel"], subject=g["subject"], messages=g["messages"])
        for g in ordered_groups
        if g["messages"]  # every message in this thread was empty (see above) -- drop the whole group
    ]

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

    last_message = max(rows, key=lambda r: r[6])
    return ConversationDetail(
        person_key=person_key,
        name=name,
        channel=last_message[2],
        last_message_at=last_message[6].isoformat(),
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
