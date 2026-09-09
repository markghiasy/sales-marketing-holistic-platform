"""Tier 2 of the noise parser (build plan §9): "have I ever replied to
this sender? how recently, how often?" — a relational signal, no model
call. Built on the contact_stats/contact_reciprocity views
(db/migrations/0002_graph_views.sql), which already compute this from
message_participant — no new schema.

No caller yet: Block C's triage inbox is the eventual consumer and
doesn't exist yet. This module is infrastructure for when it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ReplySignal:
    sent_count: int | None
    received_count: int | None
    reciprocity_ratio: float | None
    last_contact_at: datetime | None


def reply_signal(cur, contact_key: str) -> ReplySignal:
    cur.execute(
        """
        select s.sent_count, s.received_count, r.reciprocity_ratio, s.last_contact_at
        from contact_stats s
        left join contact_reciprocity r on r.contact_key = s.contact_key
        where s.contact_key = %s
        """,
        (contact_key,),
    )
    row = cur.fetchone()
    if row is None:
        return ReplySignal(None, None, None, None)
    sent_count, received_count, reciprocity_ratio, last_contact_at = row
    return ReplySignal(sent_count, received_count, reciprocity_ratio, last_contact_at)
