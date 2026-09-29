"""A bounded explanation graph; candidate matches never mutate the fact graph."""


def build_strategy_map(data, query, pack):
    catalog = {n["id"]: n for n in data["nodes"]}
    sources = {e["id"]: e for e in pack["evidence"]}
    requirements = pack["coverage"]
    # Source-backed strategy records first. Keep actual subjects, not message authors.
    records = sorted(pack["records"], key=lambda r: (r["kind"] != "strategy", r["label"], r["id"]))
    strategic = [r for r in records if r["kind"] == "strategy"]
    if strategic:
        seed_ids = {eid for row in strategic for eid in row["entity_ids"]} | {data["owner_id"]}
        # Keep the commercial explanation focused; broad adjacent-role recall stays
        # available in the answer, without filling its opportunity map with bystanders.
        records = [r for r in records if set(r["entity_ids"]) <= seed_ids]
    selected, ids = [], set()
    for row in records:
        entities = set(row["entity_ids"])
        if not entities <= catalog.keys() or not set(row["evidence_ids"]) <= sources.keys():
            continue
        if len(ids | entities) > 18 or len(selected) >= 24:
            continue
        selected.append(row)
        ids |= entities
    shown_refs = {eid for row in selected for eid in row["evidence_ids"]}
    requirements = [
        {**r, "answer_status": r["status"],
         "status": "graph_omitted" if r["evidence_ids"] and not shown_refs.intersection(r["evidence_ids"]) else r["status"],
         "evidence_ids": sorted(shown_refs.intersection(r["evidence_ids"])),
         "omitted_evidence_count": len(set(r["evidence_ids"]) - shown_refs)}
        for r in requirements
    ]
    nodes = [{"id": i, "name": catalog[i]["name"], "kind": catalog[i]["kind"]} for i in sorted(ids)]
    edges = []
    for row in selected:
        if row["kind"] == "claim":
            edges.append({"id": "relation:" + row["id"], "source": row["source"], "target": row["target"],
                          "label": row["label"], "kind": "relationship", "active": row.get("active", True),
                          "status": row.get("status", "confirmed"), "evidence_ids": row["evidence_ids"]})
    for requirement in requirements:
        rid = "requirement:" + requirement["id"]
        nodes.append({"id": rid, "name": requirement["label"], "kind": "requirement"})
        matched = set(requirement["evidence_ids"])
        bound = {}
        for row in selected:
            if not matched.intersection(row["evidence_ids"]):
                continue
            targets = [row["subject_id"]] if row["kind"] == "strategy" else row["entity_ids"]
            for target in targets:
                if target != data["owner_id"]:
                    bound.setdefault(target, set()).update(matched.intersection(row["evidence_ids"]))
        for target, refs in sorted(bound.items()):
            edges.append({"id": rid + ":" + target, "source": rid, "target": target,
                          "label": "Related evidence; validate fit", "kind": "candidate", "evidence_ids": sorted(refs)})
    refs = {eid for row in selected for eid in row["evidence_ids"]}
    return {"nodes": nodes, "edges": edges, "requirements": requirements, "records": selected,
            "evidence": [sources[e] for e in sorted(refs)], "as_of": query.as_of.isoformat(),
            "mode": query.mode, "omitted_records": len(pack["records"]) - len(selected),
            "note": "Dashed links are query-specific text matches, not verified suitability or relationships. Shared projects/companies do not prove acquaintance; paths do not prove introduction willingness."}
