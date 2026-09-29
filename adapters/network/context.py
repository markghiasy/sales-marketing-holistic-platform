"""Read-only entity lenses; work and communications are deliberately separate."""

from .model import GraphQuery, timestamp
from .projection import build_snapshot, eligible_claims
from .search import contact_tags


def entity_context(data, query: GraphQuery):
    nodes = {n["id"]: n for n in data["nodes"]}
    node = nodes[query.focus]
    q = query.model_copy(
        update={
            "view": "explorer",
            "search": "",
            "function": "",
            "organization": "",
            "project": "",
            "expand": "",
        }
    )
    evidence = {e["id"]: e for e in data["evidence"] if timestamp(e["at"]) <= q.as_of}
    claims = [
        c
        for c in eligible_claims(data, q)
        if c["evidence_ids"] and all(eid in evidence for eid in c["evidence_ids"])
    ]
    related = [c for c in claims if query.focus in (c["source"], c["target"])]
    snapshot = build_snapshot(data, q, 0)
    people = {p["id"]: p for p in snapshot["ranked_contacts"]}
    tags = contact_tags(data, q)
    member_ids = {c["source"] for c in related if c["target"] == query.focus}
    member_ids.discard(data["owner_id"])
    work = [
        r
        for r in data.get("work_records", [])
        if timestamp(r["observed_at"]) <= q.as_of
        and (r["project_id"] == query.focus or r["person_id"] == query.focus)
    ]
    evidence = {e["id"]: e for e in data["evidence"] if timestamp(e["at"]) <= q.as_of}
    work = [
        r for r in work if r["evidence_ids"] and all(eid in evidence for eid in r["evidence_ids"])
    ]
    members = [
        {
            **people[key],
            "tags": tags.get(key, []),
            "areas": sorted({r["area"] for r in work if r["person_id"] == key}),
            "deliveries": sum(r["person_id"] == key and r["status"] == "delivered" for r in work),
        }
        for key in member_ids
        if key in people
    ]
    members.sort(key=lambda p: (-p["current_activity"], p["id"]))
    # Shared contexts are explicit two-edge paths, not inferred friendships.
    owner_context = {
        c["target"]
        for c in claims
        if c["source"] == data["owner_id"] and nodes[c["target"]]["kind"] != "person"
    }
    contexts = [
        {
            "entity": nodes[c["target"]],
            "shared_with_owner": c["target"] in owner_context,
            "evidence_ids": c["evidence_ids"],
        }
        for c in related
        if c["source"] == query.focus and nodes[c["target"]]["kind"] != "person"
    ]
    return {
        "entity": node,
        "kind": node["kind"],
        "as_of": q.as_of.isoformat(),
        "members": members,
        "contexts": contexts,
        "work": work,
        "deliveries": sum(r["status"] == "delivered" for r in work),
        "follow_ups": [
            {**r, "overdue": bool(r.get("due") and r["due"] < q.as_of.date().isoformat())}
            for r in work
            if r["status"] != "delivered"
        ],
        "claims": related,
        "tags": tags.get(query.focus, []),
        "coverage": "Synthetic records only. Activity is communication with the owner, not project contribution. Deliveries are recorded updates, not independently verified outcomes.",
    }
