"""Small-corpus, evidence-first retrieval, independent of canvas/activity limits.

Lexical matches are candidate signals, not entailment or capability verification.
The source-pack byte bound is separate from the provider's exact token preflight.
"""

import json
import re
from collections import defaultdict, deque

from .model import timestamp
from .profiles import eligible_assertions
from .projection import eligible_claims


def tokens(text):
    return set(re.findall(r"[^\W_]+", text.casefold()))


def matches(text, term):
    words = tokens(term)
    return bool(words) and words <= tokens(text)


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class NetworkRetrieval:
    def __init__(self, data, query):
        self.query = query
        self.owner = data["owner_id"]
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.evidence = {e["id"]: e for e in data["evidence"] if timestamp(e["at"]) <= query.as_of}
        self.records = {}
        self.text = {}
        self.by_entity = defaultdict(list)
        self.adjacency = defaultdict(list)
        for claim in eligible_claims(data, query):
            self._add("claim", claim, [claim["source"], claim["target"]], claim["relation"])
        # Profile tags stay confirmed even when hypotheses are visible on the graph.
        confirmed = query.model_copy(update={"include_pending": False})
        for profile in eligible_claims({"claims": data.get("profile_assertions", [])}, confirmed):
            self._add("profile", profile, [profile["person_id"]], profile["label"])
        for assertion in eligible_assertions(data, query):
            entities = [assertion["subject_id"]]
            if assertion.get("context_id") and assertion["context_id"] not in entities:
                entities.append(assertion["context_id"])
            self._add("strategy", assertion, entities, assertion["label"])
        for work in data.get("work_records", []):
            if timestamp(work["observed_at"]) <= query.as_of:
                self._add(
                    "work",
                    work,
                    [work["person_id"], work["project_id"]],
                    work["area"] + ": " + work["title"],
                )

    def _add(self, kind, item, entities, label):
        refs = list(dict.fromkeys(item["evidence_ids"]))
        if (
            not refs
            or not all(e in self.evidence for e in refs)
            or not all(e in self.nodes for e in entities)
        ):
            return
        key = kind + ":" + item["id"]
        fields = (
            "source",
            "target",
            "relation",
            "observed_at",
            "valid_from",
            "valid_to",
            "end_observed_at",
            "active",
            "status",
            "due",
            "area",
            "person_id",
            "project_id",
            "subject_id",
            "claimant_id",
            "context_id",
            "facet",
            "basis",
            "quote",
            "reviewed_at",
        )
        record = {k: item[k] for k in fields if k in item}
        record.update(id=key, kind=kind, label=label, entity_ids=entities, evidence_ids=refs)
        if kind == "claim":
            record["claim_id"] = item["id"]
            for a, b in [(item["source"], item["target"]), (item["target"], item["source"])]:
                self.adjacency[a].append((b, key))
        self.records[key] = record
        self.text[key] = " ".join(
            [
                label,
                *(self.nodes[e]["name"] for e in entities),
                *(self.evidence[e]["text"] for e in refs),
            ]
        )
        for entity in entities:
            self.by_entity[entity].append(key)

    def _order(self, key):
        r = self.records[key]
        # IDs are provenance, not relevance. Semantic ordering survives source renaming.
        return (
            r["label"].casefold(),
            tuple(self.nodes[e]["name"] for e in r["entity_ids"]),
            r["observed_at"],
            key,
        )

    def people(self, terms):
        terms = list(dict.fromkeys(t.strip() for t in terms if t.strip()))
        people, units = [], set()
        candidates = [
            n for n in self.nodes.values() if n["kind"] == "person" and n["id"] != self.owner
        ]
        for person in candidates:
            related = self.by_entity[person["id"]]
            matched = [
                t
                for t in terms
                if matches(person["name"], t) or any(matches(self.text[k], t) for k in related)
            ]
            if terms and not matched:
                continue
            selected = [
                k
                for k in related
                if not terms
                or any(matches(self.text[k], t) for t in terms)
                or any(matches(person["name"], t) for t in terms)
            ]
            units.update(selected)
            people.append(
                {
                    "id": person["id"],
                    "name": person["name"],
                    "matched_terms": matched,
                    "missing_terms": [t for t in terms if t not in matched],
                    "unit_ids": sorted(selected, key=self._order),
                    "score": len(matched),
                }
            )
        # Business needs belong to organizations/initiatives, not message authors.
        # Recall these records independently instead of granting them to a contact.
        contexts = []
        for key, record in self.records.items():
            if record["kind"] != "strategy" or self.nodes[record["subject_id"]]["kind"] == "person":
                continue
            if not terms or any(matches(self.text[key], t) for t in terms):
                units.add(key)
                contexts.append(record["subject_id"])
        people.sort(key=lambda p: (-p["score"], p["name"].casefold(), p["id"]))
        return {
            "people": people,
            "contexts": sorted(set(contexts)),
            "unit_ids": sorted(units, key=self._order),
            "terms": terms,
            "scanned_people": len(candidates),
            "total_matches": len(people),
            "semantics": "OR candidate recall over names, sourced facts, work and excerpts. Matched terms do not prove capability or satisfy all requirements.",
        }

    def context(self, entity_id):
        return {
            "entity_id": entity_id,
            "unit_ids": sorted(self.by_entity[entity_id], key=self._order),
            "terms": [],
            "mode": self.query.mode,
        }

    def _person_edge(self, key):
        record = self.records[key]
        return (
            record.get("status") == "confirmed"
            and record.get("active")
            and all(self.nodes[e]["kind"] == "person" for e in record["entity_ids"])
            and record["relation"]
            in {
                "In contact",
                "Collaborates with",
                "Introduced",
                "Advises",
                "Reports to",
                "Client of",
            }
        )

    def neighborhood(self, entity_id, depth):
        if not 1 <= depth <= 3:
            raise ValueError("Neighborhood depth must be 1–3")
        paths, signatures = [], set()
        # A second person-only traversal retains a supported contact path even
        # when a shorter/shared-context path reaches the same endpoint first.
        for person_only in (True, False):
            queue, visited = deque([([entity_id], [])]), {entity_id}
            while queue:
                nodes, units = queue.popleft()
                if len(units) >= depth or (nodes[-1] == self.owner and entity_id != self.owner):
                    continue
                for other, key in sorted(
                    self.adjacency[nodes[-1]], key=lambda edge: self._order(edge[1])
                ):
                    if other in visited or (person_only and not self._person_edge(key)):
                        continue
                    visited.add(other)
                    new_nodes, new_units = [*nodes, other], [*units, key]
                    queue.append((new_nodes, new_units))
                    signature = tuple(new_units)
                    if signature in signatures:
                        continue
                    signatures.add(signature)
                    kind = (
                        "person_connections"
                        if all(self._person_edge(k) for k in new_units)
                        else "shared_context"
                    )
                    if (
                        all(self.nodes[n]["kind"] == "person" for n in new_nodes)
                        and kind != "person_connections"
                    ):
                        kind = "historical_or_unconfirmed"
                    paths.append({"node_ids": new_nodes, "unit_ids": new_units, "kind": kind})
        return {
            "paths": paths,
            "unit_ids": sorted({k for p in paths for k in p["unit_ids"]}, key=self._order),
            "terms": [],
            "depth": depth,
            "mode": self.query.mode,
        }

    def pack(self, results, requirements, max_bytes=28000):
        pool = set().union(*(set(r.get("unit_ids", [])) for r in results)) if results else set()
        searched_terms = {t.casefold() for r in results for t in r.get("terms", [])}
        terms = list(dict.fromkeys(t for r in results for t in r.get("terms", [])))
        all_paths = []
        for result in results:
            for path in result.get("paths", []):
                if path not in all_paths:
                    all_paths.append(path)
        candidates = [([k], None) for k in sorted(pool, key=self._order)] + [
            (p["unit_ids"], p) for p in all_paths
        ]
        # Global recall may find outside leads. Only directly scoped records
        # count as evidence about a selected project's/organization's own work.
        scope_entity = (
            self.query.focus if self.nodes[self.query.focus]["kind"] != "person" else None
        )
        coverage_pool = {
            k for k in pool if scope_entity is None or scope_entity in self.records[k]["entity_ids"]
        }
        hits = {
            r["id"]: {k for k in coverage_pool if any(matches(self.text[k], t) for t in r["terms"])}
            for r in requirements
        }
        selected, selected_paths, covered = set(), [], set()

        def core(keys, paths):
            refs = {e for k in keys for e in self.records[k]["evidence_ids"]}
            return {
                "records": [self.records[k] for k in sorted(keys, key=self._order)],
                "evidence": [self.evidence[e] for e in sorted(refs)],
                "paths": paths,
            }

        while candidates:

            def priority(bundle, covered=covered):
                keys, path = bundle
                newly_covered = sum(
                    bool(set(keys) & keys_hit) and req_id not in covered
                    for req_id, keys_hit in hits.items()
                )
                relevance = sum(any(matches(self.text[k], t) for k in keys) for t in terms)
                return (-newly_covered, -relevance, 0 if path else 1, self._order(keys[-1]))

            candidates.sort(key=priority)
            keys, path = candidates.pop(0)
            next_keys = selected | set(keys)
            next_paths = [*selected_paths, path] if path else selected_paths
            if encoded_size(core(next_keys, next_paths)) > max_bytes:
                continue
            selected, selected_paths = next_keys, next_paths
            covered = {rid for rid, keys_hit in hits.items() if keys_hit & selected}
        result = core(selected, selected_paths)
        coverage = []
        for requirement in requirements:
            found = hits[requirement["id"]]
            retained = found & selected
            searched = bool(requirement["terms"]) and all(
                t.casefold() in searched_terms for t in requirement["terms"]
            )
            status = (
                "matching_evidence"
                if retained
                else "budget_omitted"
                if found
                else "searched_no_match"
                if searched
                else "not_searched"
            )
            coverage.append(
                {
                    **requirement,
                    "status": status,
                    "scope_entity_id": scope_entity,
                    "evidence_ids": sorted(
                        {e for k in retained for e in self.records[k]["evidence_ids"]}
                    ),
                }
            )
        result["coverage"] = coverage
        result["budget"] = {
            "limit_bytes": max_bytes,
            "bytes": encoded_size(core(selected, selected_paths)),
            "candidate_records": len(pool),
            "selected_records": len(selected),
            "omitted_records": len(pool - selected),
            "omitted_paths": len(all_paths) - len(selected_paths),
        }
        result["scope"] = {
            "as_of": self.query.as_of.isoformat(),
            "focus": self.query.focus,
            "mode": self.query.mode,
            "include_pending": self.query.include_pending,
            "scanned_people": max((r.get("scanned_people", 0) for r in results), default=0),
            "note": "Coverage means matching text was retrieved, not verified expertise. No external search; observed synthetic records only.",
        }
        return result
