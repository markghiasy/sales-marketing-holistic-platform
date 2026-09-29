from copy import deepcopy

import pytest

from adapters.network.model import GraphQuery, timestamp
from adapters.network.scenario import load_scenario


def test_default_strategy_fixture_attributes_company_need_to_company():
    data = load_scenario()
    assert data.get("strategic_assertions"), "Default scenario must include strategic assertions"
    from adapters.network.profiles import eligible_assertions

    rows = eligible_assertions(data, GraphQuery())
    need = next(r for r in rows if r["id"] == "strategy:atlas-pilot")
    assert need["subject_id"] == "org:atlas"
    assert need["claimant_id"] == "person:alex"
    assert need["context_id"] == "project:harbour"
    role = next(r for r in rows if r["id"] == "strategy:alex-evaluator")
    assert "no budget authority" in role["quote"]
    reported = next(r for r in rows if r["id"] == "strategy:northline-report")
    assert reported["subject_id"] == "org:north"
    assert reported["claimant_id"] == "person:maya"
    assert reported["basis"] == "reported"


def test_custom_scenario_does_not_merge_strategy(tmp_path):
    path = tmp_path / "custom.json"
    path.write_text('{"nodes": []}', encoding="utf-8")
    assert load_scenario(path) == {"nodes": []}


def strategy_data():
    data = load_scenario()
    assert data.get("strategic_assertions"), "Strategy fixture missing"
    return data


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "pending"},
        {"status": "rejected"},
        {"observed_at": "2026-09-28T00:00:00Z"},
        {"valid_from": "2026-09-28T00:00:00Z"},
        {"valid_to": "2026-09-27T12:00:00Z"},
        {"quote": "This quotation was invented."},
        {"subject_id": "person:missing"},
        {"context_id": "project:missing"},
        {"claimant_id": "person:missing"},
        {"evidence_ids": ["source:missing"]},
        {"basis": "inferred"},
        {"valid_from": "not-a-date"},
        {"subject_id": "person:ben", "basis": "self_declared"},
    ],
)
def test_ineligible_assertions_cannot_enter_retrieval(changes):
    data = strategy_data()
    from adapters.network.profiles import eligible_assertions

    row = deepcopy(data["strategic_assertions"][0])
    row.update(changes)
    data["strategic_assertions"] = [row]
    assert eligible_assertions(data, GraphQuery(include_pending=True)) == []


def test_future_source_is_hidden_even_from_pending_review():
    data = strategy_data()
    from adapters.network.profiles import eligible_assertions

    row = data["strategic_assertions"][0]
    row["status"] = "pending"
    data["strategic_assertions"] = [row]
    source = next(e for e in data["evidence"] if e["id"] in row["evidence_ids"])
    source["at"] = "2026-09-28T00:00:00Z"
    assert eligible_assertions(data, GraphQuery(), include_pending=True) == []


def test_history_shows_expired_but_never_future_and_review_is_explicit():
    data = strategy_data()
    from adapters.network.profiles import eligible_assertions, profile_context

    current = eligible_assertions(data, GraphQuery())
    assert "strategy:expired-need" not in {r["id"] for r in current}
    history = eligible_assertions(data, GraphQuery(mode="history"))
    expired = next(r for r in history if r["id"] == "strategy:expired-need")
    assert expired["active"] is False
    pending = deepcopy(data["strategic_assertions"][0])
    pending.update(id="strategy:pending", status="pending")
    data["strategic_assertions"].append(pending)
    normal = profile_context(data, GraphQuery(focus="org:atlas"))
    review = profile_context(data, GraphQuery(focus="org:atlas", include_pending=True))
    assert "strategy:pending" not in {r["id"] for r in normal["assertions"]}
    assert "strategy:pending" in {r["id"] for r in review["assertions"]}
    assert {e["id"] for e in review["evidence"]} == {
        eid for r in review["assertions"] for eid in r["evidence_ids"]
    }
    assert {"org:atlas", "person:alex", "project:harbour"} <= {n["id"] for n in review["entities"]}


def candidate(data):
    row = data["strategic_assertions"][0]
    return {
        key: row[key]
        for key in (
            "subject_id",
            "facet",
            "label",
            "context_id",
            "basis",
            "valid_from",
            "valid_to",
            "quote",
        )
    } | {"evidence_id": row["evidence_ids"][0]}


def test_extraction_is_bounded_and_only_proposes_pending_with_source_author():
    data = strategy_data()
    from adapters.network.profiles import Extraction, prepare_extraction, validate_extraction

    query = GraphQuery(focus="org:atlas")
    payload = prepare_extraction(data, query)
    assert payload["evidence"]
    assert all(e["synthetic"] and e["author_id"] for e in payload["evidence"])
    result = Extraction(assertions=[candidate(data)])
    rows = validate_extraction(data, query, result, "test-model")
    assert rows[0]["status"] == "pending"
    assert rows[0]["claimant_id"] == "person:alex"
    assert timestamp(rows[0]["observed_at"]) == query.as_of
    assert rows[0]["model"] == "test-model"
    assert rows[0]["id"] not in {r["id"] for r in data["strategic_assertions"]}
    with pytest.raises(ValueError):
        Extraction(assertions=[candidate(data)] * 13)


@pytest.mark.parametrize(
    "changes",
    [
        {"quote": "not an exact quotation"},
        {"subject_id": "person:missing"},
        {"context_id": "org:missing"},
        {"evidence_id": "source:missing"},
        {"basis": "inferred"},
        {"label": "x" * 501},
        {"subject_id": "person:ben", "basis": "self_declared"},
        {"valid_from": "2026-09-28T00:00:00Z"},
        {"valid_from": "2026-09-26T00:00:00Z", "valid_to": "2026-09-25T00:00:00Z"},
        {"status": "confirmed"},
        {"claimant_id": "person:ben"},
    ],
)
def test_extraction_rejects_fabricated_and_unbounded_candidates(changes):
    data = strategy_data()
    from adapters.network.profiles import validate_extraction

    item = candidate(data)
    item.update(changes)
    with pytest.raises(ValueError):
        validate_extraction(data, GraphQuery(focus="org:atlas"), {"assertions": [item]}, "test")


def test_reported_claim_does_not_reassign_subject_to_author():
    data = strategy_data()
    from adapters.network.profiles import validate_extraction

    row = next(r for r in data["strategic_assertions"] if r["id"] == "strategy:northline-report")
    data["strategic_assertions"].remove(row)
    data["strategic_assertions"].insert(0, row)
    result = validate_extraction(
        data, GraphQuery(focus="org:north"), {"assertions": [candidate(data)]}, "test"
    )
    assert result[0]["subject_id"] == "org:north"
    assert result[0]["claimant_id"] == "person:maya"


def test_review_projection_preserves_prior_status_and_rejected_audit():
    data = strategy_data()
    from adapters.network.profiles import eligible_assertions, profile_context, validate_assertion

    original = data["strategic_assertions"][0]
    data["strategic_reviews"] = [
        {
            "id": original["id"],
            "at": "2026-09-27T11:00:00Z",
            "status": "rejected",
            "subject_id": original["subject_id"],
        }
    ]
    earlier = GraphQuery(as_of="2026-09-27T10:00:00Z", focus="org:atlas")
    assert original["id"] in {r["id"] for r in eligible_assertions(data, earlier)}
    assert original["id"] not in {r["id"] for r in eligible_assertions(data, GraphQuery())}
    review = profile_context(data, GraphQuery(focus="org:atlas", include_pending=True))
    rejected = next(r for r in review["assertions"] if r["id"] == original["id"])
    assert rejected["status"] == "rejected"
    assert rejected["reviewed_at"] == "2026-09-27T11:00:00Z"
    invalid = dict(original, subject_id="person:ben")
    with pytest.raises(ValueError):
        validate_assertion(data, invalid)


def test_extraction_cannot_use_future_or_unprovided_evidence():
    data = strategy_data()
    from adapters.network.profiles import validate_extraction

    item = candidate(data)
    with pytest.raises(ValueError):
        validate_extraction(data, GraphQuery(focus="person:ben"), {"assertions": [item]}, "test")
    source = next(e for e in data["evidence"] if e["id"] == item["evidence_id"])
    source["at"] = "2026-09-28T09:00:00Z"
    with pytest.raises(ValueError):
        validate_extraction(data, GraphQuery(focus="org:atlas"), {"assertions": [item]}, "test")


def test_claimant_must_equal_known_evidence_author():
    data = strategy_data()
    from adapters.network.profiles import validate_assertion

    row = dict(data["strategic_assertions"][0], claimant_id="person:ben")
    with pytest.raises(ValueError):
        validate_assertion(data, row)
    row = data["strategic_assertions"][0]
    source = next(e for e in data["evidence"] if e["id"] in row["evidence_ids"])
    source["author_id"] = "person:missing"
    with pytest.raises(ValueError):
        validate_assertion(data, row)


def test_all_authored_examples_have_valid_existing_references():
    data = strategy_data()
    from adapters.network.profiles import validate_assertion

    for row in data["strategic_assertions"]:
        validated = validate_assertion(data, row)
        assert validated["origin"] == "authored_pre_reviewed_example"
        assert validated["synthetic"] is True
