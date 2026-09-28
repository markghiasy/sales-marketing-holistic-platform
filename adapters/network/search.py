"""Evidence-backed contact discovery for the synthetic demo; no model calls.

The deliberately bounded language parser exposes every interpreted condition and
abstains on unconsumed terms rather than silently weakening a business request.
"""

import re
from urllib.parse import urlencode

from .model import GraphQuery, timestamp
from .projection import build_snapshot, eligible_claims


def contact_tags(data, query):
    nodes = {n["id"]: n for n in data["nodes"]}
    tags = {n["id"]: [] for n in data["nodes"] if n["kind"] == "person"}
    evidence = {e["id"]: e for e in data["evidence"] if timestamp(e["at"]) <= query.as_of}

    def add(person, kind, label, assertion, relation=""):
        refs = [eid for eid in assertion["evidence_ids"] if eid in evidence]
        if person not in tags or not refs:
            return
        tags[person].append(
            {
                "id": assertion["id"],
                "kind": kind,
                "label": label,
                "relation": relation,
                "evidence_ids": refs,
                "observed_at": assertion["observed_at"],
                "valid_from": assertion.get("valid_from"),
                "valid_to": assertion.get("valid_to"),
                "status": "confirmed",
            }
        )

    # Search and badges always use confirmed assertions, with the same time policy as the graph.
    q = query.model_copy(update={"include_pending": False, "mode": "current"})
    for claim in eligible_claims(data, q):
        source, target = claim["source"], claim["target"]
        if nodes[target]["kind"] in ("organization", "project"):
            add(source, nodes[target]["kind"], nodes[target]["name"], claim, claim["relation"])
        if claim["relation"] == "Client of" and target == data["owner_id"]:
            add(source, "relationship", "Client", claim, claim["relation"])
        if claim["relation"] == "Collaborates with" and data["owner_id"] in (source, target):
            add(
                target if source == data["owner_id"] else source,
                "relationship",
                "Collaborator",
                claim,
                claim["relation"],
            )
    profiles = {"claims": data.get("profile_assertions", [])}
    for assertion in eligible_claims(profiles, q):
        add(assertion["person_id"], assertion["kind"], assertion["label"], assertion)
    order = {"relationship": 0, "function": 1, "industry": 2, "organization": 3, "project": 4}
    for items in tags.values():
        items.sort(key=lambda t: (order[t["kind"]], t["label"], t["id"]))
    return tags


ALIASES = {
    ("function", "Accounting"): ["accountants?", "accounting", "finance", "会计", "财务"],
    ("function", "Legal"): ["lawyers?", "legal", "律师", "法律"],
    ("function", "Engineering"): ["engineers?", "engineering", "工程师", "工程"],
    ("function", "Research"): ["researchers?", "research", "研究员", "研究"],
    ("function", "Investment"): ["investors?", "investment", "投资人", "投资"],
    ("function", "Operations"): ["operations?", "运营"],
    ("function", "Sales"): ["sales", "销售"],
    ("function", "Design"): ["designers?", "design", "设计师", "设计"],
    ("industry", "Logistics"): ["logistics", "物流"],
    ("relationship", "Collaborator"): [
        "collaborators?",
        "collaborated(?: with me)?(?: before)?",
        "(?:i |we )?(?:have )?worked with(?: me)?(?: before)?",
        "(?:之前|以前)?(?:跟我|和我)?合作过",
        "合作伙伴",
    ],
    ("relationship", "Client"): ["clients?", "customers?", "客户"],
}


def interpret(text, data):
    aliases = [(kind, value, alias) for (kind, value), items in ALIASES.items() for alias in items]
    for node in data["nodes"]:
        if node["id"] == data["owner_id"]:
            continue
        if node["kind"] == "person":
            for name in [node["name"], *node["name"].split()]:
                aliases.append(("name", name, re.escape(name)))
        else:
            for name in [node["name"], node["name"].split()[0]]:
                aliases.append((node["kind"], node["name"], re.escape(name)))
    candidates = []
    for kind, value, alias in aliases:
        # English boundaries prevent "legal" matching a longer unrelated word.
        pattern = r"(?<![a-z])(?:" + alias + r")(?![a-z])"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidates.append((match.start(), match.end(), kind, value))
    used, criteria = set(), []
    modifiers = list(
        re.finditer(r"preferably|ideally|prefer|最好|优先|must|required|必须", text, re.IGNORECASE)
    )
    for start, end, kind, value in sorted(candidates, key=lambda c: -(c[1] - c[0])):
        span = set(range(start, end))
        if used & span:
            continue
        used |= span
        before = [m for m in modifiers if m.start() < start]
        mode = "require"
        if before and before[-1].group().lower() in (
            "preferably",
            "ideally",
            "prefer",
            "最好",
            "优先",
        ):
            mode = "prefer"
        if not any(
            c["kind"] == kind and c["value"] == value and c["mode"] == mode for c in criteria
        ):
            criteria.append({"kind": kind, "value": value, "mode": mode})
    rest = "".join(" " if i in used else c for i, c in enumerate(text.lower()))
    rest = re.sub(
        r"\b(find|show|search|for|me|an?|the|with|in|at|from|on|and|who|has|have|knows?|can|help|need|looking|"
        r"experience|experienced|expertise|people|contacts?|someone|person|please|"
        r"preferably|ideally|prefer|must|required|be|is|a|my|network)\b",
        " ",
        rest,
    )
    rest = re.sub(
        r"帮我|找一下|找|查找|懂|擅长|有|经验|的|人|最好|优先|必须|请|以及|并且|在", " ", rest
    )
    unresolved = re.sub(r"[\s,，.。?!？！:：;；]+", " ", rest).strip()
    for criterion in criteria:
        if criterion["kind"] != "name":
            continue
        target = re.escape(criterion["value"])
        if re.search(
            r"(?:knows?|worked with|collaborated with)[^,.!?;]*\b" + target + r"\b",
            text,
            re.IGNORECASE,
        ):
            unresolved = "Relationships to a named person need clarification: " + text
    if re.search(
        r"\b(not|without|except|exclude|excluding)\b|不要|排除|不是|不懂|不在|没有",
        text,
        re.IGNORECASE,
    ):
        unresolved = "Exclusions need clarification: " + text
    if not criteria and not unresolved:
        unresolved = "Add a name, function, industry, organization, project or relationship."
    return sorted(criteria, key=lambda c: (c["mode"], c["kind"], c["value"])), unresolved


def search_contacts(data, query, text, version):
    criteria, unresolved = interpret(text, data)
    result = {
        "status": "needs_clarification" if unresolved else "ok",
        "query": text,
        "criteria": criteria,
        "unresolved": unresolved,
        "results": [],
        "version": version,
        "as_of": query.as_of.isoformat(),
        "backend": "synthetic",
        "interpretation": "bounded_language",
    }
    if unresolved:
        return result
    tags = contact_tags(data, query)
    snapshot = build_snapshot(data, GraphQuery(as_of=query.as_of), version)
    for person in snapshot["ranked_contacts"]:
        reasons, missing, preference_matches = [], [], 0
        for criterion in criteria:
            if criterion["kind"] == "name":
                matched = criterion["value"].casefold() in person["name"].casefold()
                matching_tags = tags.get(person["id"], [])
            else:
                matching_tags = [
                    t
                    for t in tags.get(person["id"], [])
                    if t["kind"] == criterion["kind"] and t["label"] == criterion["value"]
                ]
                matched = bool(matching_tags)
            if not matched:
                missing.append(criterion)
                continue
            preference_matches += criterion["mode"] == "prefer"
            reasons.append(
                {
                    **criterion,
                    "text": (
                        "Name matches "
                        if criterion["kind"] == "name"
                        else "Supported " + criterion["kind"] + ": "
                    )
                    + criterion["value"],
                    "evidence_ids": sorted(
                        {eid for tag in matching_tags for eid in tag["evidence_ids"]}
                    ),
                }
            )
        if any(c["mode"] == "require" for c in missing):
            continue
        params = {"focus": person["id"], "origin": person["id"], "as_of": query.as_of.isoformat()}
        result["results"].append(
            {
                "id": person["id"],
                "name": person["name"],
                "role": person["role"],
                "tags": tags.get(person["id"], []),
                "reasons": reasons,
                "unmet_preferences": [c["value"] for c in missing],
                "preference_matches": preference_matches,
                "recent_activity": person["current_activity"],
                "network_url": "/network?" + urlencode(params),
                "conversation_url": "/inbox?" + urlencode(params),
            }
        )
    result["results"].sort(key=lambda p: (-p["preference_matches"], -p["recent_activity"], p["id"]))
    return result
