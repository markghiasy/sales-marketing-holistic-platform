import json

from adapters.network.model import GraphQuery
from adapters.network.scenario import load_scenario


def engine(data=None, **query):
    from adapters.network.retrieval import NetworkRetrieval

    return NetworkRetrieval(data or load_scenario(), GraphQuery(**query))


def test_all_candidates_are_searched_and_work_text_is_retrievable():
    retriever = engine()
    all_people = retriever.people([])
    assert all_people["scanned_people"] == 24
    assert len(all_people["people"]) == 24  # no activity-ordered top twelve
    result = retriever.people(["warehouse cost assumptions"])
    assert result["people"][0]["id"] == "person:priya"
    assert result["people"][0]["matched_terms"] == ["warehouse cost assumptions"]
    assert any(retriever.records[k]["kind"] == "work" for k in result["unit_ids"])


def test_quiet_but_relevant_contact_is_not_pruned_by_activity():
    data = load_scenario()
    data["messages"] = [m for m in data["messages"] if m["contact_id"] != "person:priya"]
    assert engine(data).people(["warehouse cost assumptions"])["people"][0]["id"] == "person:priya"


def test_missing_or_future_sources_are_not_searchable():
    data = load_scenario()
    data["evidence"] = [e for e in data["evidence"] if e["id"] != "evidence:work:cost-model"]
    assert not engine(data).people(["warehouse cost assumptions"])["people"]
    assert not engine(as_of="2026-02-01T00:00:00Z").people(["warehouse cost assumptions"])["people"]


def test_history_keeps_effective_dates_and_known_correction():
    current = engine().context("person:alex")
    historical = engine(mode="history")
    units = historical.context("person:alex")["unit_ids"]
    old = next(r for r in historical.records.values() if r.get("claim_id") == "job-alex-old")
    assert old["id"] not in current["unit_ids"]
    assert old["id"] in units and old["active"] is False
    assert old["valid_to"] == "2026-08-01T00:00:00Z"
    assert "evidence:job-alex-new" in old["evidence_ids"]
    early = engine(mode="history", as_of="2026-08-15T00:00:00Z")
    old = next(r for r in early.records.values() if r.get("claim_id") == "job-alex-old")
    assert old["valid_to"] is None
    assert "evidence:job-alex-new" not in old["evidence_ids"]


def test_paths_are_complete_and_do_not_use_owner_as_a_bridge():
    r = engine()
    result = r.neighborhood("person:sam", 3)
    assert result["paths"]
    for path in result["paths"]:
        assert "person:owner" not in path["node_ids"][1:-1]
        assert len(path["unit_ids"]) == len(path["node_ids"]) - 1
        for index, key in enumerate(path["unit_ids"]):
            record = r.records[key]
            assert {record["source"], record["target"]} == set(path["node_ids"][index : index + 2])
        if any(r.nodes[key]["kind"] != "person" for key in path["node_ids"]):
            assert path["kind"] == "shared_context"


def test_pack_deduplicates_sources_preserves_path_closure_and_reports_budget():
    r = engine()
    result = r.neighborhood("person:sam", 3)
    pack = r.pack([result, result], [], max_bytes=5000)
    assert pack["budget"]["bytes"] <= 5000
    assert pack["budget"]["omitted_records"] > 0
    records = {u["id"]: u for u in pack["records"]}
    evidence = {e["id"] for e in pack["evidence"]}
    assert len(evidence) == len(pack["evidence"])
    for path in pack["paths"]:
        assert set(path["unit_ids"]) <= records.keys()
        assert all(set(records[k]["evidence_ids"]) <= evidence for k in path["unit_ids"])
    assert all(set(u["evidence_ids"]) <= evidence for u in records.values())


def test_coverage_distinguishes_unknown_from_budget_omission():
    r = engine()
    requirements = [
        {"id": "cost", "label": "Cost model", "terms": ["warehouse cost assumptions"]},
        {"id": "security", "label": "Security", "terms": ["adversarial testing"]},
        {"id": "law", "label": "Legal", "terms": ["Legal"]},
    ]
    hits = r.people(["warehouse cost assumptions", "adversarial testing"])
    pack = r.pack([hits], requirements, max_bytes=100)
    statuses = {c["id"]: c["status"] for c in pack["coverage"]}
    assert statuses == {
        "cost": "budget_omitted",
        "security": "searched_no_match",
        "law": "not_searched",
    }
    full = r.pack([hits], requirements)
    assert full["coverage"][0]["status"] == "matching_evidence"
    assert full["coverage"][0]["evidence_ids"]


def test_renaming_evidence_ids_does_not_change_people_ranking():
    data = load_scenario()
    expected = [p["id"] for p in engine(data).people(["Research", "Engineering"])["people"]]
    raw = json.dumps(data)
    for i, evidence in enumerate(data["evidence"]):
        raw = raw.replace('"' + evidence["id"] + '"', '"renamed:' + str(999 - i) + '"')
    actual = [
        p["id"] for p in engine(json.loads(raw)).people(["Research", "Engineering"])["people"]
    ]
    assert actual == expected


def test_context_view_preserves_history_mode():
    from adapters.network.context import entity_context

    result = entity_context(load_scenario(), GraphQuery(focus="person:alex", mode="history"))
    assert any(c["id"] == "job-alex-old" for c in result["claims"])


def test_agent_supplements_unsearched_requirements_once_and_passes_coverage():
    from adapters.network.agent import AgentRequest, NetworkAgent

    class Provider:
        available, model = True, "test"
        payload = None

        def structured(self, schema, system, payload):
            if schema.__name__ == "RetrievalPlan":
                result = {
                    "intent": "Find work support",
                    "lookups": [{"kind": "people", "terms": ["Engineering"]}],
                    "requirements": [
                        {
                            "id": "cost",
                            "label": "Cost modelling",
                            "terms": ["warehouse cost assumptions"],
                        }
                    ],
                }
            else:
                self.payload = payload
                result = {"summary": "Validate this adjacent lead.", "findings": []}
            return schema.model_validate(result), {"input_tokens": 10, "output_tokens": 5}

    provider = Provider()
    result = NetworkAgent(provider).answer(
        load_scenario(), AgentRequest(question="Who can help?"), 1
    )
    assert len(result["trace"]) == 2
    assert result["trace"][-1]["supplemental"] is True
    assert result["retrieval"]["coverage"][0]["status"] == "matching_evidence"
    assert any(e["id"] == "evidence:work:cost-model" for e in provider.payload["evidence"])
    assert provider.payload["records"]


def test_agent_request_preserves_history_mode():
    from adapters.network.agent import AgentRequest

    assert AgentRequest(question="Previous employer?", mode="history").mode == "history"


def test_provider_counts_exact_strict_request_and_blocks_oversize(monkeypatch):
    from types import SimpleNamespace

    import anthropic
    import pytest

    from adapters.network.agent import AgentUnavailable, ClaudeProvider, RetrievalPlan

    calls = []
    count = 100

    class Client:
        messages = None

        def __enter__(self):
            self.messages = self
            return self

        def __exit__(self, *args):
            pass

        def count_tokens(self, **kwargs):
            calls.append(("count", kwargs))
            return SimpleNamespace(input_tokens=count)

        def create(self, **kwargs):
            calls.append(("generate", kwargs))
            return SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="submit",
                        input={
                            "intent": "Read",
                            "lookups": [{"kind": "people", "terms": ["Engineering"]}],
                        },
                    )
                ],
                usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            )

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: Client())
    provider = ClaudeProvider({"ANTHROPIC_API_KEY": "synthetic"})
    provider.structured(RetrievalPlan, "Test", {"question": "Find people"})
    assert [c[0] for c in calls] == ["count", "generate"]
    assert calls[0][1] == {k: v for k, v in calls[1][1].items() if k != "max_tokens"}
    assert calls[0][1]["tools"][0]["strict"] is True
    count = 1_000_000
    calls.clear()
    with pytest.raises(AgentUnavailable, match="budget"):
        provider.structured(RetrievalPlan, "Test", {"question": "Find people"})
    assert len(calls) == 1


def test_strict_schema_keeps_nonempty_citations_and_describes_upper_bounds():
    from adapters.network.agent import Answer, strict_tool_schema

    schema = strict_tool_schema(Answer.model_json_schema())
    citations = schema["$defs"]["Finding"]["properties"]["evidence_ids"]
    assert citations["minItems"] == 1
    assert "8" in citations["description"]


def test_context_drops_work_without_sources_and_search_links_keep_history():
    from adapters.network.context import entity_context
    from adapters.network.search import search_contacts

    data = load_scenario()
    data["work_records"][0]["evidence_ids"] = []
    view = entity_context(data, GraphQuery(focus="project:harbour"))
    assert all(w["evidence_ids"] for w in view["work"])
    result = search_contacts(data, GraphQuery(mode="history"), "Alex Morgan", 1)
    assert all("mode=history" in p["network_url"] for p in result["results"])


def test_project_coverage_does_not_count_another_projects_deliveries():
    r = engine(focus="project:harbour")
    hits = r.people(["delivered"])
    pack = r.pack([hits], [{"id": "delivery", "label": "Harbour delivery", "terms": ["delivered"]}])
    assert pack["coverage"][0]["evidence_ids"] == ["evidence:work:finance-pack"]
    assert pack["coverage"][0]["scope_entity_id"] == "project:harbour"
