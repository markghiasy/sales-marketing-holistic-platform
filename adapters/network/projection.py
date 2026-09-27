"""Pure graph projection: time, provenance and display bounds, without model calls."""
import math
from collections import defaultdict
from datetime import datetime

from .model import GraphQuery, GraphSnapshot, ScenarioData, timestamp


def sessions(messages: list[dict], now: datetime) -> list[dict]:
    eligible = {m["id"]: m for m in messages if m.get("direct") and timestamp(m["at"]) <= now}
    groups = defaultdict(list)
    for message in eligible.values():
        groups[(message["contact_id"], message["channel"])].append(message)
    result = []
    for (contact, channel), rows in groups.items():
        last = None
        for row in sorted(rows, key=lambda m: (timestamp(m["at"]), m["id"])):
            at = timestamp(row["at"])
            if last is None or (at - last["at"]).total_seconds() > 1800:
                last = {"contact_id": contact, "channel": channel, "at": at, "directions": set()}
                result.append(last)
            last["at"] = at
            last["directions"].add(row["direction"])
    return result


def activity(messages: list[dict], now: datetime, half_life: float, scale: float = 4) -> float:
    if half_life <= 0 or scale <= 0:
        raise ValueError("Half-life and scale must be positive")
    return sum(2 ** (-((now - s["at"]).total_seconds() / 86400) / half_life) for s in sessions(messages, now))


def eligible_claims(data: ScenarioData, query: GraphQuery) -> list[dict]:
    result = []
    for claim in data["claims"]:
        if claim["status"] == "rejected" or (claim["status"] == "pending" and not query.include_pending):
            continue
        if timestamp(claim["observed_at"]) > query.as_of:
            continue
        end = claim.get("valid_to")
        # A later correction cannot retroactively leak into an earlier knowledge snapshot.
        if claim.get("end_observed_at") and timestamp(claim["end_observed_at"]) > query.as_of:
            end = None
        active = (not claim.get("valid_from") or timestamp(claim["valid_from"]) <= query.as_of) and (not end or query.as_of < timestamp(end))
        if not active and query.mode != "history":
            continue
        item = {**claim, "valid_to": end, "active": active}
        # The unseen correction timestamp is not exposed either.
        if not end:
            item.pop("end_observed_at", None)
        result.append(item)
    return result


def build_snapshot(data: ScenarioData, query: GraphQuery, version: int) -> GraphSnapshot:
    nodes = {n["id"]: n for n in data["nodes"]}
    if query.focus not in nodes:
        raise KeyError(query.focus)
    claims = eligible_claims(data, query)
    scored = []
    for node in data["nodes"]:
        if node["kind"] != "person" or node["id"] == data["owner_id"]:
            continue
        related = [c for c in claims if c["source"] == node["id"] or c["target"] == node["id"]]
        if query.search.casefold() not in (node["name"] + " " + node.get("role", "")).casefold():
            continue
        if query.function and query.function not in node.get("functions", []):
            continue
        if query.project and not any(c["target"] == query.project and c["source"] == node["id"] and c["status"] == "confirmed" for c in related):
            continue
        if query.organization and not any(c["target"] == query.organization and c["source"] == node["id"] and c["status"] == "confirmed" for c in related):
            continue
        messages = [m for m in data["messages"] if m["contact_id"] == node["id"]]
        history_sessions = sessions(messages, query.as_of)
        reciprocal = sum(s["directions"] == {"in", "out"} for s in history_sessions)
        fast = activity(messages, query.as_of, 30)
        slow = activity(messages, query.as_of, 180)
        dates = [s["at"] for s in history_sessions]
        coverage = node.get("coverage", "observed channels only")
        history = {"sessions": len(history_sessions), "reciprocal_sessions": reciprocal,
                   "active_days": len({t.date() for t in dates}), "channels": sorted({s["channel"] for s in history_sessions}),
                   "duration_days": (max(dates) - min(dates)).days if dates else 0,
                   "coverage": coverage, "label": "Observed two-way exchange" if reciprocal else "No observed two-way exchange"}
        reasons = []
        if query.project:
            reasons.append("Confirmed member of " + nodes[query.project]["name"])
        if query.function:
            reasons.append("Function: " + query.function)
        reasons.append("Recent direct activity" if query.mode == "current" else "Longer-term interaction history")
        scored.append({**node, "current_activity": round(100 * (1 - math.exp(-fast / 4)), 1),
                       "history_activity": round(100 * (1 - math.exp(-slow / 4)), 1),
                       "history": history, "reasons": reasons,
                       "evidence_ids": sorted({i for c in related for i in c["evidence_ids"]})})
    metric = "current_activity" if query.mode == "current" else "history_activity"
    scored.sort(key=lambda n: (-n[metric], n["id"]))
    filtered = bool(query.search or query.function or query.organization or query.project)
    anchors = {n["id"] for n in scored} if filtered else set(nodes)
    anchors.add(query.focus)
    if filtered:
        anchors.update(c["target"] for c in claims if c["source"] in anchors and nodes[c["target"]]["kind"] != "person")
        anchors.add(data["owner_id"])
    pool = [c for c in claims if c["source"] in anchors and c["target"] in anchors]
    if query.view == "compact" or query.expand:
        reached = {query.focus}
        for _ in range(2 if query.expand else 1):
            reached |= {endpoint for c in pool if c["source"] in reached or c["target"] in reached for endpoint in (c["source"], c["target"])}
        anchors &= reached
        pool = [c for c in pool if c["source"] in anchors and c["target"] in anchors]
    node_limit, edge_limit = (8, 12) if query.view == "compact" else (50, 100)
    priority = [query.focus, data["owner_id"]] + [n["id"] for n in scored] + sorted(anchors)
    ordered = list(dict.fromkeys(n for n in priority if n in anchors))
    selected = ordered[:node_limit]
    selected_set = set(selected)
    edges = [c for c in pool if c["source"] in selected_set and c["target"] in selected_set][:edge_limit]
    omitted = {"nodes": len(anchors) - len(selected), "edges": len(pool) - len(edges)}
    return {"version": version, "computed_at": query.as_of.isoformat(), "as_of": query.as_of.isoformat(),
            "owner_id": data["owner_id"], "focus_id": query.focus, "backend": "synthetic",
            "nodes": [nodes[n] for n in selected], "edges": edges, "ranked_contacts": scored,
            "omitted_counts": omitted, "truncated": any(omitted.values()),
            "options": {"functions": sorted({f for n in nodes.values() for f in n.get("functions", [])}),
                        "organizations": [n for n in nodes.values() if n["kind"] == "organization"],
                        "projects": [n for n in nodes.values() if n["kind"] == "project"]}}
