"""Deduplicated reply statistics, optionally across a bounded candidate cluster.

Counts across unconfirmed identities are explicitly provisional. No person,
identity or merge-log rows are changed by this read path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .resolution.clusters import candidate_cluster


@dataclass
class ReplySignal:
    sent_count: int | None
    received_count: int | None
    reciprocity_ratio: float | None
    last_contact_at: datetime | None
    provisional: bool = False
    identity_count: int = 0
    aggregation_reason: str = "no_candidates"
    identity_ids: tuple[str, ...] = ()


def reply_signal(cur, contact_key: str) -> ReplySignal:
    cluster = candidate_cluster(cur, contact_key)
    ids = cluster.aggregate_ids
    cur.execute(
        """
        select count(*) filter (where direction='outbound'),
               count(*) filter (where direction='inbound'), max(sent_at)
        from message m where exists
          (select 1 from message_participant mp
           where mp.message_id=m.id and mp.identity_id=any(%s::uuid[]))
        """,
        (ids,),
    )
    row = cur.fetchone()
    if row is None or row[2] is None:
        return ReplySignal(None, None, None, None, cluster.allowed, len(ids), cluster.reason, tuple(ids))
    sent_count, received_count, last_contact_at = row
    ratio = min(sent_count, received_count) / max(sent_count, received_count)
    return ReplySignal(sent_count, received_count, ratio, last_contact_at,
                       cluster.allowed, len(ids), cluster.reason, tuple(ids))
