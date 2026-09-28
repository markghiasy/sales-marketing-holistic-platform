from adapters.network.model import GraphQuery
from adapters.network.projection import build_snapshot
from adapters.network.scenario import load_scenario
from scripts.network_demo import create_app


def test_scope_snapshot_replaces_hops_and_preserves_overlapping_paths():
    result = build_snapshot(
        load_scenario(),
        GraphQuery(focus="person:sam", expand="person:sam", scopes="explicit,organization"),
        1,
    )
    assert result["expansion"]["scopes"] == ["explicit", "organization"]
    candidates = {p["id"]: p for p in result["ranked_contacts"]}
    assert "person:priya" in candidates
    assert "person:grace" in candidates
    assert "person:maya" not in candidates
    ids = {n["id"] for n in result["nodes"]}
    edges = {e["id"] for e in result["edges"]}
    for person in candidates.values():
        for path in person["relationship_scope"]["paths"]:
            assert set(path["node_ids"]) <= ids
            assert set(path["claim_ids"]) <= edges
    assert candidates["person:grace"]["relationship_scope"]["interaction"]["sessions"] is None


def test_old_hop_activity_parameters_do_not_suppress_other_scope_people():
    data = load_scenario()
    clean = build_snapshot(
        data, GraphQuery(focus="person:sam", expand="person:sam", scopes="organization"), 1
    )
    old = build_snapshot(
        data,
        GraphQuery(
            focus="person:sam",
            expand="person:sam",
            scopes="organization",
            depth=1,
            min_activity=100,
        ),
        1,
    )
    assert clean["ranked_contacts"] == old["ranked_contacts"]
    assert "person:grace" in {p["id"] for p in old["ranked_contacts"]}


def test_empty_scope_and_invalid_scope_api():
    client = create_app(testing=True).test_client()
    empty = client.get("/network/graph.json?focus=person:sam&expand=person:sam&scopes=").get_json()
    assert [n["id"] for n in empty["nodes"]] == ["person:sam"]
    assert empty["edges"] == []
    assert client.get("/network/graph.json?scopes=very_close").status_code == 400


def test_message_only_direct_path_evidence_resolves_with_date():
    app = create_app(testing=True)
    store = app.extensions["network_store"]
    data = store._data
    data["claims"] = [
        c for c in data["claims"] if {c["source"], c["target"]} != {"person:owner", "person:maya"}
    ]
    client = app.test_client()
    snap = client.get(
        "/network/graph.json?focus=person:owner&expand=person:owner&scopes=direct"
    ).get_json()
    person = next(p for p in snap["ranked_contacts"] if p["id"] == "person:maya")
    refs = person["relationship_scope"]["paths"][0]["evidence_ids"]
    assert refs
    for eid in refs:
        response = client.get("/network/evidence/" + eid + ".json")
        assert response.status_code == 200
        assert response.get_json()["text"]
    assert (
        client.get("/network/evidence/" + refs[0] + ".json?as_of=2026-01-01T00:00:00Z").status_code
        == 404
    )


def test_evidence_endpoint_respects_source_knowledge_dates():
    for field in ("observed_at", "known_at"):
        app = create_app(testing=True)
        data = app.extensions["network_store"]._data
        data["messages"].append(
            {
                "id": "late-import",
                "at": "2026-01-01T00:00:00Z",
                field: "2026-09-20T00:00:00Z",
                "text": "Previously unknown contact",
                "direct": True,
                "contact_id": "person:maya",
                "channel": "outlook",
                "direction": "in",
            }
        )
        client = app.test_client()
        assert (
            client.get("/network/evidence/late-import.json?as_of=2026-08-01T00:00:00Z").status_code
            == 404
        )
        assert client.get("/network/evidence/late-import.json").status_code == 200


def test_explicit_message_participants_follow_identity_bindings():
    data = load_scenario()
    data["nodes"].append({"id": "person:alias", "name": "Alias", "kind": "person"})
    data["identity_bindings"] = {"person:alias": "person:sam"}
    data["messages"].append(
        {
            "id": "pair-source",
            "at": "2026-09-20T00:00:00Z",
            "text": "Explicit direct pair source",
            "direct": True,
            "contact_id": "person:priya",
            "participant_ids": ["person:alias", "person:priya"],
            "channel": "outlook",
            "direction": "in",
        }
    )
    query = GraphQuery(focus="person:sam", expand="person:sam", scopes="direct")
    result = build_snapshot(data, query, 1)
    priya = next(p for p in result["ranked_contacts"] if p["id"] == "person:priya")
    assert priya["relationship_scope"]["interaction"]["sessions"] == 1
    data["identity_bindings"]["person:alias"] = "person:priya"
    result = build_snapshot(data, query, 1)
    assert not any(
        e.get("origin") == "messages" and e["source"] == e["target"] for e in result["edges"]
    )
