from scripts.network_demo import create_app


def test_contacts_have_separate_supported_tags_and_current_topic():
    client = create_app(testing=True).test_client()
    person = client.get("/inbox/conversation/person:maya.json").json
    labels = {t["label"] for t in person["tags"]}
    assert {"Accounting", "Logistics", "Client", "Collaborator", "Harbour expansion"} <= labels
    assert person["topic"] != "Accounting"
    for tag in person["tags"]:
        assert tag["evidence_ids"]
        assert all(
            client.get(f"/network/evidence/{eid}.json").status_code == 200
            for eid in tag["evidence_ids"]
        )


def test_business_search_separates_requirements_and_preferences():
    client = create_app(testing=True).test_client()
    response = client.get(
        "/network/search.json",
        query_string={
            "q": "Find an accountant with logistics experience, preferably someone I worked with before"
        },
    )
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "ok"
    assert [p["id"] for p in data["results"]] == ["person:maya", "person:priya"]
    assert any(c["mode"] == "prefer" and c["value"] == "Collaborator" for c in data["criteria"])
    assert data["results"][0]["preference_matches"] == 1
    assert data["results"][1]["preference_matches"] == 0
    assert all(r["evidence_ids"] for r in data["results"][0]["reasons"])


def test_required_collaboration_chinese_and_evidence():
    client = create_app(testing=True).test_client()
    data = client.get(
        "/network/search.json", query_string={"q": "找懂物流的会计，必须之前跟我合作过"}
    ).json
    assert data["status"] == "ok"
    assert [p["id"] for p in data["results"]] == ["person:maya"]
    for person in data["results"]:
        for reason in person["reasons"]:
            assert reason["evidence_ids"]
    assert "focus=person%3Amaya" in data["results"][0]["network_url"]


def test_search_does_not_silently_drop_unknown_conditions_or_negation():
    client = create_app(testing=True).test_client()
    for text in [
        "Find accountants in Sydney",
        "Find accountants who speak French",
        "not an accountant",
    ]:
        data = client.get("/network/search.json", query_string={"q": text}).json
        assert data["status"] == "needs_clarification"
        assert data["results"] == []
        assert data["unresolved"]


def test_search_does_not_change_named_relationship_targets_or_job_titles():
    client = create_app(testing=True).test_client()
    for text in ["Find people who know Maya", "Find people who worked with Maya", "Find a CFO"]:
        data = client.get("/network/search.json", query_string={"q": text}).json
        assert data["status"] == "needs_clarification", text
        assert not data["results"]


def test_search_names_keeps_distinct_identities_and_current_roles():
    client = create_app(testing=True).test_client()
    data = client.get("/network/search.json", query_string={"q": "Alex Morgan"}).json
    assert {p["id"] for p in data["results"]} == {"person:alex", "person:alex2"}
    tags = next(p for p in data["results"] if p["id"] == "person:alex")["tags"]
    assert any(t["label"] == "Atlas Logistics" and t["relation"] == "Works at" for t in tags)
    assert not any(t["label"] == "Northline Advisory" and t["relation"] == "Works at" for t in tags)


def test_search_validation_empty_results_and_observation_time():
    client = create_app(testing=True).test_client()
    assert client.get("/network/search.json?q=").status_code == 400
    assert client.get("/network/search.json", query_string={"q": "x" * 601}).status_code == 400
    assert client.get("/network/search.json?q=accountants&as_of=bad").status_code == 400
    assert client.get("/network/search.json?q=lawyers%20in%20Atlas").json["results"] == []
    data = client.get(
        "/network/search.json", query_string={"q": "Atlas", "as_of": "2026-08-20T12:00:00Z"}
    ).json
    assert "person:alex" not in {p["id"] for p in data["results"]}
