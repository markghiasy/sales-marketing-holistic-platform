from scripts.network_demo import create_app


def test_demo_routes_and_validation():
    client = create_app(testing=True).test_client()
    assert client.get("/network/graph.json").json["backend"] == "synthetic"
    assert client.get("/network/graph.json?view=huge").status_code == 400
    assert client.get("/network/graph.json?as_of=garbage").status_code == 400
    assert client.get("/network/graph.json?focus=missing").status_code == 404
    assert client.get("/network/evidence/missing.json").status_code == 404
    assert client.get("/inbox/conversation/person:maya.json").json["name"] == "Maya Chen"
    assert client.post("/outlook/connect").status_code == 404
    assert client.post("/inbox/conversation/person:maya/hide").status_code == 404


def test_reply_and_reset_versions_are_monotonic_and_content_resets():
    client = create_app(testing=True).test_client()
    before = client.get("/network/graph.json").json
    response = client.post("/network/demo/reply").json
    after = client.get("/network/graph.json").json
    assert after["version"] == response["version"] > before["version"]
    maya = lambda s: next(p for p in s["ranked_contacts"] if p["id"] == "person:maya")
    assert maya(after)["current_activity"] > maya(before)["current_activity"]
    client.post("/network/demo/reset")
    reset = client.get("/network/graph.json").json
    assert reset["version"] > after["version"]
    assert maya(reset)["current_activity"] == maya(before)["current_activity"]


def test_apps_do_not_share_scenario_state_and_sse_announces_snapshot():
    first = create_app(testing=True).test_client()
    second = create_app(testing=True).test_client()
    first.post("/network/demo/reply")
    assert second.get("/network/graph.json").json["version"] == 1
    response = first.get("/network/events", buffered=False)
    assert b'"version": 2' in next(response.response)
    response.close()


def test_evidence_is_restricted_to_observation_time():
    client = create_app(testing=True).test_client()
    assert (
        client.get(
            "/network/evidence/evidence:job-alex-new.json?as_of=2026-08-20T00:00:00Z"
        ).status_code
        == 404
    )
    assert client.get("/network/evidence/evidence:job-alex-new.json").json["synthetic"] is True


def test_outbound_fixture_messages_match_inbox_direction_contract():
    client = create_app(testing=True).test_client()
    messages = client.get("/inbox/conversation/person:maya.json").json["messages"]
    assert {m["sender"] for m in messages} == {"you", "them"}
