"""Constructed-case comparison, not an independent retrieval benchmark."""

import argparse
import csv
import json
from pathlib import Path

from adapters.network.model import GraphQuery, timestamp
from adapters.network.projection import build_snapshot
from adapters.network.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]


def run_evaluation():
    data = load_scenario()
    cases = json.loads((ROOT / "docs/research/network-demo/scenarios.json").read_text())
    results = []
    for case in cases:
        q = GraphQuery(**case["query"])
        for policy in ["filter_only", "filter_recency", "temporal_context"]:
            if policy == "temporal_context":
                ids = [p["id"] for p in build_snapshot(data, q, 1)["ranked_contacts"]]
            else:
                contacts = [
                    n
                    for n in data["nodes"]
                    if n["kind"] == "person" and n["id"] != data["owner_id"]
                ]
                contacts = [
                    n
                    for n in contacts
                    if (not q.function or q.function in n["functions"])
                    and (not q.organization or "org:" + n.get("cluster", "") == q.organization)
                    and q.search.casefold() in (n["name"] + " " + n["role"]).casefold()
                ]
                # These limited contact-card baselines have no project graph or historical roles.
                contacts.sort(key=lambda n: n["id"])
                if policy == "filter_recency":

                    def latest(node, as_of=q.as_of):
                        dates = [
                            timestamp(m["at"])
                            for m in data["messages"]
                            if m["contact_id"] == node["id"]
                            and timestamp(m["at"]) <= as_of
                            and m.get("direct")
                        ]
                        return max(dates).timestamp() if dates else 0

                    contacts.sort(key=lambda n: -latest(n))
                ids = [n["id"] for n in contacts]
            expected = set(case["expected_ids"])
            retrieved = set(ids)
            hits = len(expected & retrieved)
            results.append(
                {
                    "scenario": case["id"],
                    "policy": policy,
                    "backend": "synthetic",
                    "status": "executed",
                    "expected_ids": sorted(expected),
                    "returned_ids": ids,
                    "exact_set": retrieved == expected,
                    "precision": hits / len(retrieved)
                    if retrieved
                    else (1.0 if not expected else 0.0),
                    "recall": hits / len(expected) if expected else 1.0,
                }
            )
    full = build_snapshot(data, GraphQuery(), 1)
    evidence_ids = {e["id"] for e in data["evidence"]}
    checks = {
        "dangling_evidence_links": sum(
            i not in evidence_ids for c in full["edges"] for i in c["evidence_ids"]
        ),
        "pending_or_rejected_in_default": sum(c["status"] != "confirmed" for c in full["edges"]),
        "separate_client_and_collaborator": {"client-maya", "collab-maya"}.issubset(
            {e["id"] for e in full["edges"]}
        ),
    }
    summary = {
        p: {
            "exact_sets": sum(r["exact_set"] for r in results if r["policy"] == p),
            "cases": len(cases),
        }
        for p in ["filter_only", "filter_recency", "temporal_context"]
    }
    return {
        "design": "Seven hand-authored diagnostic cases; baselines deliberately lack project/time relations. Not a held-out benchmark.",
        "settings": {"fast_half_life_days": 30, "slow_half_life_days": 180, "saturation_scale": 4},
        "summary": summary,
        "integrity_checks": checks,
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/research/network-demo")
    args = parser.parse_args()
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    report = run_evaluation()
    (target / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (target / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report["results"][0]))
        writer.writeheader()
        writer.writerows(report["results"])
    print(
        json.dumps(
            {"summary": report["summary"], "integrity_checks": report["integrity_checks"]}, indent=2
        )
    )
