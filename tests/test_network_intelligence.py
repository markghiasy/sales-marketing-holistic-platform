import pytest

from adapters.network.model import GraphQuery
from adapters.network.projection import build_snapshot
from adapters.network.scenario import load_scenario


def test_expansion_escapes_name_filter_without_traversing_owner_hub():
    data = load_scenario()
    result = build_snapshot(
        data, GraphQuery(focus="person:sam", search="sam", expand="person:sam", depth=2), 1
    )
    ids = {n["id"] for n in result["nodes"]}
    assert "person:priya" in ids
    assert "person:grace" in ids  # shared university, not a proven acquaintance
    assert "person:maya" not in ids  # cannot traverse owner into every contact
    assert {p["id"] for p in result["ranked_contacts"]} == ids - {
        "person:owner",
        "org:uni",
        "org:atlas",
        "project:bridge",
        "project:harbour",
    }
    assert result["expansion"]["depth"] == 2


def test_depth_is_separate_from_activity_and_bounded():
    with pytest.raises(ValueError):
        GraphQuery(depth=4)
    result = build_snapshot(
        load_scenario(),
        GraphQuery(focus="person:sam", expand="person:sam", depth=2, min_activity=90),
        1,
    )
    assert all(
        p["id"] == "person:sam" or p["current_activity"] >= 90 for p in result["ranked_contacts"]
    )


def test_project_view_uses_work_evidence_and_date():
    from adapters.network.context import entity_context

    data = load_scenario()
    current = entity_context(data, GraphQuery(focus="project:harbour"))
    assert current["kind"] == "project"
    assert current["work"]
    assert current["deliveries"] >= 1
    assert any(r["status"] == "blocked" for r in current["work"])
    assert all(r["evidence_ids"] for r in current["work"])
    old = entity_context(data, GraphQuery(focus="project:harbour", as_of="2026-02-01T00:00:00Z"))
    assert not old["work"]


def test_agent_unconfigured_and_cross_origin_never_calls_provider():
    from scripts.network_demo import create_app

    app = create_app(testing=True)
    client = app.test_client()
    assert client.post("/network/agent.json", json={"question": "Who can help?"}).status_code == 503
    assert (
        client.post(
            "/network/agent.json",
            json={"question": "Who?"},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )


class FakeProvider:
    available = True
    model = "fake-test-provider"

    def __init__(self, bad_reference=False):
        self.payloads = []
        self.bad_reference = bad_reference

    def structured(self, schema, system, payload):
        self.payloads.append(payload)
        if schema.__name__ == "RetrievalPlan":
            result = {
                "intent": "Find engineering evidence",
                "lookups": [{"kind": "people", "terms": ["Engineering"]}],
            }
        else:
            result = {
                "summary": "Engineering is adjacent; security expertise needs validation.",
                "findings": [
                    {
                        "text": "Amir lists Engineering.",
                        "entity_ids": ["person:amir"],
                        "evidence_ids": [
                            "invented" if self.bad_reference else "evidence:profile:amir:function"
                        ],
                    }
                ],
                "gaps": ["No verified AI security testing expertise in this evidence."],
                "next_steps": ["Ask whether Amir can help validate the technical scope."],
            }
        return schema.model_validate(result), {"input_tokens": 20, "output_tokens": 10}


def test_agent_uses_retrieval_then_validates_citations_and_budget():
    from adapters.network.agent import AgentRequest, AgentUnavailable, NetworkAgent

    provider = FakeProvider()
    agent = NetworkAgent(provider, max_requests=1)
    result = agent.answer(load_scenario(), AgentRequest(question="Who can help with Cybertest?"), 7)
    assert len(provider.payloads) == 2
    assert result["backend"] == "anthropic" and result["version"] == 7
    assert result["usage"]["input_tokens"] == 40
    assert result["evidence"][0]["id"] == "evidence:profile:amir:function"
    assert all("ANTHROPIC" not in str(p) for p in provider.payloads)
    with pytest.raises(AgentUnavailable):
        agent.answer(load_scenario(), AgentRequest(question="Again"), 7)
    with pytest.raises(ValueError, match="Unsupported answer reference"):
        NetworkAgent(FakeProvider(True)).answer(load_scenario(), AgentRequest(question="Who?"), 7)


def test_agent_historical_evidence_request_bounds_and_safe_error():
    from scripts.network_demo import create_app

    provider = FakeProvider()
    client = create_app(testing=True, agent_provider=provider).test_client()
    assert client.post("/network/agent.json", json={"question": "x" * 2001}).status_code == 400
    response = client.post(
        "/network/agent.json", json={"question": "Engineering", "as_of": "2026-01-02T00:00:00Z"}
    )
    assert response.status_code == 502  # No source available then; fake citation is rejected.
    assert "key" not in response.get_data(as_text=True)
    assert not provider.payloads[-1]["evidence"]


def test_valid_unicode_history_and_unrelated_entity_reference():
    from adapters.network.agent import AgentRequest, NetworkAgent
    from scripts.network_demo import create_app

    client = create_app(testing=True, agent_provider=FakeProvider()).test_client()
    response = client.post(
        "/network/agent.json",
        json={
            "question": "找工程师",
            "history": [{"question": "问" * 2000, "answer": "答" * 3000} for _ in range(4)],
        },
    )
    assert response.status_code == 200

    class WrongPerson(FakeProvider):
        def structured(self, schema, system, payload):
            result, usage = super().structured(schema, system, payload)
            if schema.__name__ == "Answer":
                result.findings[0].entity_ids = ["person:grace"]
            return result, usage

    with pytest.raises(ValueError, match="Unsupported answer reference"):
        NetworkAgent(WrongPerson()).answer(load_scenario(), AgentRequest(question="Who?"), 1)
