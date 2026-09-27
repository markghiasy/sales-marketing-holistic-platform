from datetime import UTC, datetime

import pytest

from adapters.network.model import GraphQuery
from adapters.network.projection import activity, build_snapshot
from adapters.network.scenario import load_scenario


def snapshot(**kwargs):
    return build_snapshot(load_scenario(), GraphQuery(**kwargs), 1)


def test_time_and_review_status_are_not_silently_promoted():
    early = snapshot(as_of="2026-08-01T00:00:00Z")
    now = snapshot()
    assert "job-alex-old" in {e["id"] for e in early["edges"]}
    assert "job-alex-new" not in {e["id"] for e in early["edges"]}
    assert "job-alex-new" in {e["id"] for e in now["edges"]}
    assert "job-alex-old" not in {e["id"] for e in now["edges"]}
    assert "job-alex-advisor" in {e["id"] for e in now["edges"]}
    assert "intro-pending" not in {e["id"] for e in now["edges"]}
    assert "intro-pending" in {e["id"] for e in snapshot(include_pending=True)["edges"]}
    assert all(e["status"] != "rejected" for e in snapshot(include_pending=True)["edges"])


def test_late_evidence_is_not_known_before_observation():
    middle = snapshot(as_of="2026-08-20T00:00:00Z")
    assert "job-alex-new" not in {e["id"] for e in middle["edges"]}
    # Leaving the old role was learned in September, not in August.
    assert "job-alex-old" in {e["id"] for e in middle["edges"]}


def test_role_end_has_later_evidence_without_leaking_it_early():
    early = next(
        e for e in snapshot(as_of="2026-08-20T00:00:00Z")["edges"] if e["id"] == "job-alex-old"
    )
    later = next(e for e in snapshot(mode="history")["edges"] if e["id"] == "job-alex-old")
    assert "evidence:job-alex-new" not in early["evidence_ids"]
    assert "evidence:job-alex-new" in later["evidence_ids"]


def test_sessions_collapse_bursts_and_preserve_reciprocity():
    from adapters.network.projection import sessions

    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [
        {
            "id": "a",
            "contact_id": "p",
            "channel": "outlook",
            "direction": "in",
            "direct": True,
            "at": "2026-09-26T10:00:00Z",
        },
        {
            "id": "b",
            "contact_id": "p",
            "channel": "outlook",
            "direction": "out",
            "direct": True,
            "at": "2026-09-26T10:30:00Z",
        },
        {
            "id": "c",
            "contact_id": "p",
            "channel": "outlook",
            "direction": "in",
            "direct": True,
            "at": "2026-09-26T11:01:00Z",
        },
    ]
    result = sessions(rows, now)
    assert len(result) == 2
    assert result[0]["directions"] == {"in", "out"}


def test_names_do_not_define_identity_and_roles_are_separate():
    s = snapshot()
    alex = [n for n in s["nodes"] if n["name"] == "Alex Morgan"]
    assert {n["id"] for n in alex} == {"person:alex", "person:alex2"}
    assert {"client-maya", "collab-maya"} <= {e["id"] for e in s["edges"]}
    assert s["owner_id"] == "person:owner"
    assert snapshot(focus="person:maya")["owner_id"] == "person:owner"


def test_slices_are_bounded_consistent_and_without_dangling_edges():
    full = snapshot()
    small = snapshot(view="compact", focus="person:maya")
    assert len(small["nodes"]) <= 8 and len(small["edges"]) <= 12
    assert len(full["nodes"]) <= 50 and len(full["edges"]) <= 100
    ids = {n["id"] for n in small["nodes"]}
    assert "person:maya" in ids
    lookup = {e["id"]: e for e in full["edges"]}
    for edge in small["edges"]:
        assert edge["source"] in ids and edge["target"] in ids
        assert edge == lookup[edge["id"]]
        assert edge["evidence_ids"]


def test_filtering_returns_known_candidates_with_honest_history():
    s = snapshot(function="Accounting", project="project:harbour")
    assert {p["id"] for p in s["ranked_contacts"]} == {"person:maya", "person:priya"}
    full = snapshot()
    cold = next(p for p in full["ranked_contacts"] if p["id"] == "person:leo")
    assert cold["history"]["reciprocal_sessions"] == 0
    assert cold["history"]["label"] == "No observed two-way exchange"
    missing = next(p for p in full["ranked_contacts"] if p["id"] == "person:alex2")
    assert missing["history"]["coverage"] == "partial"


def test_activity_deduplicates_excludes_future_and_non_direct():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    base = {
        "id": "m1",
        "contact_id": "p",
        "channel": "outlook",
        "direction": "in",
        "direct": True,
        "at": "2026-08-28T00:00:00Z",
    }
    assert activity([base], now, 30) == pytest.approx(0.5)
    assert activity([base, base], now, 30) == pytest.approx(0.5)
    assert activity([{**base, "direct": False}], now, 30) == 0
    assert activity([{**base, "at": "2026-10-01T00:00:00Z"}], now, 30) == 0
    with pytest.raises(ValueError):
        activity([base], now, 0)


def test_query_validation_and_unknown_focus():
    with pytest.raises(ValueError):
        GraphQuery(view="unbounded")
    with pytest.raises(ValueError):
        GraphQuery(as_of="broken")
    with pytest.raises(KeyError):
        snapshot(focus="person:missing")


def test_explicit_identity_rebinding_and_undo_preserve_source_ids():
    data = load_scenario()
    data["identity_bindings"] = {"person:alex2": "person:alex"}
    merged = build_snapshot(data, GraphQuery(), 2)
    assert "person:alex2" not in {n["id"] for n in merged["nodes"]}
    researcher = next(e for e in merged["edges"] if e["id"] == "job-alex2")
    assert researcher["source"] == "person:alex"
    assert researcher["evidence_ids"] == ["evidence:job-alex2"]
    data["identity_bindings"] = {}
    undone = build_snapshot(data, GraphQuery(), 3)
    assert "person:alex2" in {n["id"] for n in undone["nodes"]}
    assert next(e for e in undone["edges"] if e["id"] == "job-alex2")["source"] == "person:alex2"
