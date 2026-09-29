from adapters.network.model import GraphQuery
from adapters.network.retrieval import NetworkRetrieval
from adapters.network.scenario import load_scenario
from scripts.network_demo import create_app


def strategic_data():
    data = load_scenario()
    source = {"id": "strategy:test", "channel": "outlook", "at": "2026-09-20T09:00:00Z",
              "text": "Atlas needs an AI safety pilot. I evaluate the technical scope, not budget approval.",
              "author_id": "person:alex", "synthetic": True}
    data["evidence"].append(source)
    row = {"id": "strategy:test-need", "subject_id": "org:atlas", "facet": "need",
           "label": "AI safety pilot", "context_id": "project:harbour", "basis": "reported",
           "observed_at": source["at"], "valid_from": source["at"], "valid_to": None,
           "status": "confirmed", "evidence_ids": [source["id"]],
           "quote": "Atlas needs an AI safety pilot.", "claimant_id": "person:alex", "model": "authored-demo"}
    data["strategic_assertions"] = [row]
    return data


def test_organization_need_is_searchable_without_becoming_authors_need():
    data = strategic_data()
    r = NetworkRetrieval(data, GraphQuery())
    result = r.people(["AI safety pilot"])
    records = [r.records[k] for k in result["unit_ids"] if r.records[k]["kind"] == "strategy"]
    assert len(records) == 1
    assert records[0]["subject_id"] == "org:atlas"
    assert "person:alex" not in records[0]["entity_ids"]
    assert records[0]["basis"] == "reported"


def test_pending_strategy_cannot_enter_answer_pack():
    data = strategic_data()
    data["strategic_assertions"][0]["status"] = "pending"
    r = NetworkRetrieval(data, GraphQuery(include_pending=True))
    assert not [x for x in r.records.values() if x["kind"] == "strategy"]


def test_strategy_map_distinguishes_candidate_edges_and_unknown_requirements():
    from adapters.network.strategy_map import build_strategy_map
    data = strategic_data()
    r = NetworkRetrieval(data, GraphQuery())
    requirements = [{"id": "pilot", "label": "AI pilot", "terms": ["AI safety pilot"], "priority": "require"},
                    {"id": "budget", "label": "Budget authority", "terms": ["Budget owner"], "priority": "require"}]
    pack = r.pack([r.people(["AI safety pilot", "Budget owner"])], requirements)
    result = build_strategy_map(data, GraphQuery(), pack)
    assert any(e["kind"] == "candidate" and e["target"] == "org:atlas" for e in result["edges"])
    assert not any(e["target"] == "person:alex" for e in result["edges"])
    assert next(x for x in result["requirements"] if x["id"] == "budget")["status"] == "searched_no_match"
    nodes = {n["id"] for n in result["nodes"]}
    refs = {e["id"] for e in result["evidence"]}
    assert all(e["source"] in nodes and e["target"] in nodes and set(e["evidence_ids"]) <= refs for e in result["edges"])


def test_profile_route_and_review_preserve_historical_state():
    app = create_app(testing=True)
    store = app.extensions["network_store"]
    store._data = strategic_data()
    client = app.test_client()
    old = client.get("/network/profile.json?focus=org:atlas").get_json()
    assert old and "assertions" in old
    response = client.post("/network/profile/review", json={"id": "strategy:test-need", "status": "rejected", "subject_id": "org:atlas", "version": old["version"]})
    assert response.status_code == 200
    latest = response.get_json()
    current = client.get("/network/profile.json", query_string={"focus": "org:atlas", "as_of": latest["as_of"]}).get_json()
    assert next(a for a in current["assertions"] if a["id"] == "strategy:test-need")["status"] == "rejected"
    historic = client.get("/network/profile.json?focus=org:atlas").get_json()
    assert historic["assertions"][0]["status"] == "confirmed"
    assert not [a for a in NetworkRetrieval(store.data(), GraphQuery(as_of=latest["as_of"])).records.values() if a["kind"] == "strategy"]
    assert client.post("/network/profile/review", json={"id": "strategy:test-need", "status": "confirmed", "subject_id": "org:atlas", "version": old["version"]}).status_code == 409


def test_profile_mutations_reject_cross_origin_and_bad_fields():
    client = create_app(testing=True).test_client()
    for path in ("/network/profile/review", "/network/profile/extract"):
        assert client.post(path, json={}, headers={"Origin": "https://elsewhere.example"}).status_code == 403
        assert client.post(path, data="not json").status_code == 415
    assert client.post("/network/profile/review", json={"id":"missing", "status":"admin", "version":1}).status_code == 400
    assert client.post("/network/profile/extract", json={"focus":"person:alex"}).status_code == 503


def test_long_business_question_is_accepted_by_search_entry():
    client = create_app(testing=True).test_client()
    response = client.get("/network/search.json", query_string={"q": "business goal " * 60})
    assert response.status_code == 200
    assert response.get_json()["status"] == "needs_clarification"


def test_extraction_creates_pending_proposals_and_shares_request_budget():
    class Extractor:
        available = True
        model = "fixture-extractor"
        def structured(self, schema, system, payload):
            assert schema.__name__ == "Extraction"
            source = payload["evidence"][0]
            return schema.model_validate({"assertions": [{
                "evidence_id": source["id"], "quote": source["text"],
                "subject_id": source["author_id"], "facet": "decision_role",
                "label": "Technical scope evaluator; budget approval not established",
                "context_id": "project:harbour", "basis": "self_declared",
                "valid_from": None, "valid_to": None,
            }]}), {"input_tokens": 10, "output_tokens": 20}
    app = create_app(testing=True, agent_provider=Extractor())
    store = app.extensions["network_store"]
    store._data = strategic_data()
    client = app.test_client()
    response = client.post("/network/profile/extract", json={"focus": "person:alex"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["added"] == 1 and payload["usage"]["input_tokens"] == 10
    proposed = [a for a in payload["assertions"] if a["status"] == "pending"]
    assert len(proposed) == 1
    r = NetworkRetrieval(store.data(), GraphQuery(as_of=payload["as_of"]))
    assert all(proposed[0]["id"] not in row["id"] for row in r.records.values())
    response2 = client.post("/network/profile/review", json={"id":proposed[0]["id"],"status":"confirmed","subject_id":"person:alex","version":payload["version"]})
    assert response2.status_code == 200
    r = NetworkRetrieval(store.data(), GraphQuery(as_of=response2.get_json()["as_of"]))
    assert any(proposed[0]["id"] in row["id"] for row in r.records.values())
    assert client.get("/network/agent/status.json").get_json()["remaining"] == 19


def test_failed_extraction_leaves_profile_unmodified():
    class BadExtractor:
        available = True
        model = "fixture-extractor"
        def structured(self, schema, system, payload):
            return schema.model_validate({"assertions": [{
                "evidence_id": payload["evidence"][0]["id"], "quote": "invented quotation",
                "subject_id": "person:alex", "facet": "need", "label": "Unfounded",
                "basis": "self_declared", "context_id": "",
                "valid_from": None, "valid_to": None,
            }]}), {}
    app = create_app(testing=True, agent_provider=BadExtractor())
    store = app.extensions["network_store"]
    store._data = strategic_data()
    before = store.capture()
    response = app.test_client().post("/network/profile/extract", json={"focus":"person:alex"})
    assert response.status_code == 502
    assert store.capture() == before


def test_map_does_not_claim_hidden_evidence_is_displayed():
    from adapters.network.strategy_map import build_strategy_map
    data = load_scenario()
    r = NetworkRetrieval(data, GraphQuery())
    pack = r.pack([r.people([])], [{"id":"research","label":"Research","terms":["research"],"priority":"require"}])
    result = build_strategy_map(data, GraphQuery(), pack)
    sources = {e["id"] for e in result["evidence"]}
    assert all(set(x["evidence_ids"]) <= sources for x in result["requirements"])
    assert result["omitted_records"] > 0
