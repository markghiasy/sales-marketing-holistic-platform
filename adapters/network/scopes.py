"""Evidence-backed, overlapping relationship scopes; never a familiarity score."""

from collections import defaultdict
from datetime import timedelta

from .model import GraphQuery, ScenarioData, timestamp

SCOPES = ("direct", "explicit", "project", "organization")
EXPLICIT = {"Collaborates with", "Introduced", "Possible introduction"}
PERSON_LINKS = {"In contact", "Client of", "Reports to"} | EXPLICIT
CONTEXT = {"project": {"Project member"}, "organization": {"Works at", "Advises"}}
REASONS = {
    "direct": "Recorded person-to-person contact; metrics describe this exact pair only.",
    "explicit": "Sourced collaboration or introduction relation, directly or via one person.",
    "project": "Shared project membership is context, not evidence of acquaintance.",
    "organization": "Shared affiliation is context, not guaranteed colleagues or acquaintance.",
}


def _known_source(row, now):
    return (
        bool(row.get("text", "").strip())
        and bool(row.get("at"))
        and all(
            timestamp(row[field]) <= now
            for field in ("at", "observed_at", "known_at")
            if row.get(field)
        )
    )


def _overlap(edges):
    if len(edges) < 2:
        return "not_applicable"
    starts = [timestamp(e["valid_from"]) for e in edges if e.get("valid_from")]
    ends = [timestamp(e["valid_to"]) for e in edges if e.get("valid_to")]
    if starts and ends and max(starts) >= min(ends):
        return "different_periods"
    if len(starts) < len(edges):
        return "unknown"
    return "overlapping"


def expand_scopes(data: ScenarioData, query: GraphQuery, claims: list[dict]) -> dict:
    """Return whole path bundles and pair-specific metadata within display bounds.

    ``claims`` is the existing temporal eligibility projection. Source knowledge is
    checked again here because a claim timestamp alone cannot make evidence known.
    Legacy depth and activity parameters deliberately play no role.
    """
    from .projection import sessions

    nodes = {n["id"]: n for n in data["nodes"]}
    focus, owner = query.focus, data["owner_id"]
    selected_scopes = query.scopes.split(",") if query.scopes else []
    sources = {
        s["id"]: s
        for s in data.get("evidence", []) + data.get("messages", [])
        if _known_source(s, query.as_of)
    }
    edges = {}
    for row in claims:
        ids = row.get("evidence_ids", [])
        if (
            ids
            and all(key in sources for key in ids)
            and row["source"] in nodes
            and row["target"] in nodes
        ):
            edges[row["id"]] = dict(row)

    # contact_id is owner-relative. Do not reassign these observations to a
    # nonowner focus. Explicit participant pairs can support other exact pairs.
    pair_messages = defaultdict(list)
    for row in data.get("messages", []):
        if row["id"] not in sources or not row.get("direct"):
            continue
        pair = row.get("participant_ids")
        if pair is None:
            pair = [owner, row.get("contact_id")]
        if (
            len(pair) != 2
            or len(set(pair)) != 2
            or any(n not in nodes or nodes[n]["kind"] != "person" for n in pair)
        ):
            continue
        pair_messages[tuple(sorted(pair))].append(row)
    lower = query.as_of - timedelta(days=query.scope_window) if query.scope_window else None
    interactions = {}
    for pair, rows in sorted(pair_messages.items()):
        # A single pair/channel is one grouping unit even with explicit participants.
        normalized = [{**m, "contact_id": "pair"} for m in rows]
        history = sessions(normalized, query.as_of)
        if lower:
            history = [s for s in history if s["at"] >= lower]
        dates = [s["at"] for s in history]
        interactions[pair] = {
            "sessions": len(history),
            "reciprocal_sessions": sum(s["directions"] == {"in", "out"} for s in history),
            "last_at": max(dates).isoformat() if dates else None,
            "coverage": "Observed direct messages for this exact pair only",
        }
        edge_id = "scope:messages:" + ":".join(pair)
        edges[edge_id] = {
            "id": edge_id,
            "source": pair[0],
            "target": pair[1],
            "relation": "In contact",
            "status": "confirmed",
            "origin": "messages",
            "scope": "ego_relative" if owner in pair else "world",
            "observed_at": max(timestamp(m["at"]) for m in rows).isoformat(),
            "valid_from": None,
            "valid_to": None,
            "active": True,
            "evidence_ids": sorted({m["id"] for m in rows}),
        }

    def interaction(person):
        return interactions.get(
            tuple(sorted((focus, person))),
            {
                "sessions": None,
                "reciprocal_sessions": None,
                "last_at": None,
                "coverage": "No observed direct messages for this exact pair; interaction unknown",
            },
        )

    original_claims = {c["id"]: c for c in data.get("claims", [])}

    def event_at(edge):
        # observed_at is import/review knowledge time, not the relationship event.
        if edge.get("event_at"):
            at = timestamp(edge["event_at"])
            return at if at <= query.as_of else None
        original = original_claims.get(edge["id"], edge)
        correction_ids = set(original.get("correction_evidence_ids", []))
        return max(
            (timestamp(sources[e]["at"]) for e in edge["evidence_ids"] if e not in correction_ids),
            default=None,
        )

    found = defaultdict(list)

    def add(person, scope, path_nodes, path_edges):
        if person == focus or nodes[person]["kind"] != "person":
            return
        overlap = _overlap(path_edges) if scope in CONTEXT else "not_applicable"
        if overlap == "different_periods" and query.mode != "history":
            return
        pending = any(
            e["status"] == "pending" or e["relation"] == "Possible introduction" for e in path_edges
        )
        if pending and not query.include_pending:
            return
        dates = [event_at(e) for e in path_edges] if scope not in CONTEXT else []
        # All event legs must meet the window. Recent contact with an intermediary
        # does not refresh an old collaboration with the eventual candidate.
        if lower and dates and any(at is None or at < lower for at in dates):
            return
        last = max((at for at in dates if at), default=None)
        if scope == "direct" and (interaction(person)["sessions"] or 0) < query.min_sessions:
            return
        if scope == "direct":
            label = "Recorded direct contact"
        elif scope == "explicit":
            label = (
                "Evidenced person path via " + nodes[path_nodes[1]]["name"]
                if len(path_edges) == 2
                else path_edges[0]["relation"]
            )
        else:
            label = "Project membership" if scope == "project" else "Organization affiliation"
            if len(path_edges) == 2:
                label = "Shared " + label.lower() + " via " + nodes[path_nodes[1]]["name"]
            label += {
                "unknown": " (overlap unknown)",
                "different_periods": " (different periods)",
                "overlapping": " (overlapping periods)",
            }.get(overlap, "")
        if pending:
            label += " (unconfirmed)"
        found[person].append(
            {
                "scope": scope,
                "node_ids": path_nodes,
                "claim_ids": [e["id"] for e in path_edges],
                "evidence_ids": sorted({i for e in path_edges for i in e["evidence_ids"]}),
                "status": "pending" if pending else "confirmed",
                "active": all(e.get("active", True) for e in path_edges),
                "overlap": overlap,
                "label": label,
                "last_event_at": last.isoformat() if last else None,
            }
        )

    personal = defaultdict(list)
    for edge in edges.values():
        if edge["relation"] in PERSON_LINKS and all(
            nodes[edge[k]]["kind"] == "person" for k in ("source", "target")
        ):
            personal[edge["source"]].append((edge["target"], edge))
            personal[edge["target"]].append((edge["source"], edge))
    for neighbor, first in personal[focus]:
        if "direct" in selected_scopes and first["relation"] == "In contact":
            add(neighbor, "direct", [focus, neighbor], [first])
        if "explicit" not in selected_scopes:
            continue
        if first["relation"] in EXPLICIT:
            add(neighbor, "explicit", [focus, neighbor], [first])
        if neighbor == owner and focus != owner:
            continue
        for candidate, second in personal[neighbor]:
            if candidate == focus or candidate == neighbor:
                continue
            if first["relation"] in EXPLICIT or second["relation"] in EXPLICIT:
                add(candidate, "explicit", [focus, neighbor, candidate], [first, second])

    for scope, relations in CONTEXT.items():
        if scope not in selected_scopes:
            continue
        memberships = defaultdict(list)
        for edge in edges.values():
            if (
                edge["relation"] in relations
                and nodes[edge["source"]]["kind"] == "person"
                and nodes[edge["target"]]["kind"] == scope
            ):
                memberships[edge["target"]].append(edge)
        if nodes[focus]["kind"] == scope:
            for edge in memberships[focus]:
                add(edge["source"], scope, [focus, edge["source"]], [edge])
        else:
            for context, members in memberships.items():
                for first in members:
                    if first["source"] != focus:
                        continue
                    for second in members:
                        if second["source"] != focus:
                            add(
                                second["source"],
                                scope,
                                [focus, context, second["source"]],
                                [first, second],
                            )

    def make_candidate(person, paths):
        scopes = [scope for scope in SCOPES if any(p["scope"] == scope for p in paths)]
        dates = [p["last_event_at"] for p in paths if p["last_event_at"]]
        return {
            "id": person,
            "scopes": scopes,
            "scope_reasons": [REASONS[s] for s in scopes],
            "paths": paths,
            "interaction": interaction(person),
            "last_event_at": max(dates) if dates else None,
        }

    candidates = [make_candidate(person, paths) for person, paths in found.items()]

    def sort_key(row):
        name = (nodes[row["id"]]["name"].casefold(), row["id"])
        if query.scope_sort == "name":
            return name
        if query.scope_sort == "frequency":
            count = row["interaction"]["sessions"]
            return (-(count if count is not None else -1), *name)
        date = row["last_event_at"]
        return (-(timestamp(date).timestamp() if date else float("-inf")), *name)

    candidates.sort(key=sort_key)
    node_limit, edge_limit = (8, 12) if query.view == "compact" else (50, 100)
    selected_nodes, selected_edges, retained = {focus}, set(), []
    total_nodes = {focus} | {n for paths in found.values() for p in paths for n in p["node_ids"]}
    total_edges = {e for paths in found.values() for p in paths for e in p["claim_ids"]}
    total_paths = sum(len(paths) for paths in found.values())
    for candidate in candidates:
        # A representative of every category is atomic, so bounds never silently
        # erase overlapping category labels from an included candidate.
        paths = sorted(
            candidate["paths"],
            key=lambda p: (
                SCOPES.index(p["scope"]),
                p["status"] != "confirmed",
                len(p["claim_ids"]),
                tuple(p["claim_ids"]),
            ),
        )
        representatives = {}
        for path in paths:
            representatives.setdefault(path["scope"], path)
        bundle = list(representatives.values())
        new_nodes = {n for p in bundle for n in p["node_ids"]}
        new_edges = {e for p in bundle for e in p["claim_ids"]}
        if (
            len(selected_nodes | new_nodes) > node_limit
            or len(selected_edges | new_edges) > edge_limit
        ):
            continue
        selected_nodes |= new_nodes
        selected_edges |= new_edges
        for path in paths:
            if path in bundle:
                continue
            ns, es = set(path["node_ids"]), set(path["claim_ids"])
            if len(selected_nodes | ns) <= node_limit and len(selected_edges | es) <= edge_limit:
                bundle.append(path)
                selected_nodes |= ns
                selected_edges |= es
        retained.append(make_candidate(candidate["id"], bundle))
    return {
        "nodes": [focus] + sorted(selected_nodes - {focus}),
        "edges": [edges[key] for key in sorted(selected_edges)],
        "candidates": retained,
        "counts": {scope: sum(scope in c["scopes"] for c in retained) for scope in SCOPES},
        "omitted_counts": {
            "nodes": len(total_nodes - selected_nodes),
            "edges": len(total_edges - selected_edges),
            "candidates": len(candidates) - len(retained),
            "paths": total_paths - sum(len(c["paths"]) for c in retained),
        },
        "scopes": selected_scopes,
        "window_days": query.scope_window,
        "sort": query.scope_sort,
        "min_sessions": query.min_sessions,
        "note": "Scopes overlap and are evidence categories, not closeness levels. "
        "Window applies to event scopes; session minimum applies only to direct scope. "
        "Shared contexts remain visible and do not establish interaction or acquaintance.",
    }
