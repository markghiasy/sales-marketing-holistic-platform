"""Read-only candidate identity neighbourhoods; never professional graph edges.

Density counts unique unordered pairs, including established person equivalence.
Traversal stops as soon as a ninth identity is observed: never trim a component
to make it eligible. Rejected pairs are a veto even through an alternative path.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

ACTIVE_METHODS = (
    "exact_email",
    "contact_bridge",
    "linkedin_name_company",
    "outlook_same_channel_dedupe",
)
MAX_IDENTITIES = 8
MIN_DENSITY = 0.5


@dataclass
class CandidateCluster:
    own_ids: list[str]
    member_ids: list[str]
    allowed: bool = False
    density: float | None = None
    reason: str = "no_candidates"
    suggestions: list[dict] = field(default_factory=list)
    suggestions_truncated: bool = False

    @property
    def aggregate_ids(self):
        return self.member_ids if self.allowed else self.own_ids


def candidate_cluster(cur, contact_key: str) -> CandidateCluster:
    # Two batched reads avoid one hosted-database round trip per candidate.
    cur.execute("""select i.id, coalesce(i.person_id,i.id), i.channel,
                          i.handle, i.display_name
        from identity i
        where not i.is_self and not exists
          (select 1 from contact_hidden h where h.contact_key=coalesce(i.person_id,i.id))""")
    identities = {
        str(r[0]): {"key": str(r[1]), "channel": r[2], "handle": r[3], "name": r[4]}
        for r in cur.fetchall()
    }
    effective_key = identities.get(contact_key, {}).get("key", contact_key)
    groups = defaultdict(set)
    for identity_id, data in identities.items():
        groups[data["key"]].add(identity_id)
    own = groups.get(effective_key, set())
    result = CandidateCluster(sorted(own), sorted(own))
    if not own:
        return result
    cur.execute("""select id, identity_a_id, identity_b_id, status, method, reason
        from link_candidate where status in ('pending','rejected') order by id""")
    adjacency = defaultdict(set)
    pairs, rejected, suggestions = set(), set(), []
    for cid, a, b, status, method, reason in cur.fetchall():
        a, b = str(a), str(b)
        if a == b or a not in identities or b not in identities:
            continue
        pair = tuple(sorted((a, b)))
        if status == "rejected":
            rejected.add(pair)
            continue
        if method not in ACTIVE_METHODS:
            continue
        pairs.add(pair)
        adjacency[a].add(b)
        adjacency[b].add(a)
        if (a in own) != (b in own):
            other = b if a in own else a
            info = identities[other]
            suggestions.append(
                {
                    "candidate_id": str(cid),
                    "identity_id": other,
                    "contact_key": info["key"],
                    "channel": info["channel"],
                    "handle": info["handle"],
                    "name": info["name"] or info["handle"],
                    "method": method,
                    "evidence": reason or "No evidence recorded",
                }
            )
    result.suggestions = suggestions[:50]
    result.suggestions_truncated = len(suggestions) > 50
    members, pending = set(own), list(own)
    while pending and len(members) <= MAX_IDENTITIES:
        node = pending.pop()
        neighbours = adjacency[node] | groups[identities[node]["key"]]
        for neighbour in sorted(neighbours - members):
            members.add(neighbour)
            pending.append(neighbour)
            if len(members) > MAX_IDENTITIES:
                break
    result.member_ids = sorted(members)
    if len(members) > MAX_IDENTITIES:
        result.reason = "too_large"
        return result
    if members == own:
        return result
    for a, b in combinations(sorted(members), 2):
        if identities[a]["key"] == identities[b]["key"]:
            pairs.add((a, b))
    possible = len(members) * (len(members) - 1) / 2
    result.density = sum(a in members and b in members for a, b in pairs) / possible
    if any(a in members and b in members for a, b in rejected):
        result.reason = "rejected_pair"
    elif result.density < MIN_DENSITY:
        result.reason = "sparse"
    else:
        result.allowed, result.reason = True, "eligible"
    return result
