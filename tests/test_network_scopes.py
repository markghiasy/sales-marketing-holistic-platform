import pytest
from pydantic import ValidationError

from adapters.network.model import GraphQuery
from adapters.network.projection import eligible_claims

OLD = "2026-01-01T00:00:00Z"
RECENT = "2026-09-20T10:00:00Z"


def dataset():
    return {
        "owner_id": "owner",
        "nodes": [
            {"id": key, "name": key.title(), "kind": kind}
            for key, kind in [
                ("owner", "person"),
                ("a", "person"),
                ("b", "person"),
                ("c", "person"),
                ("d", "person"),
                ("project", "project"),
                ("org", "organization"),
            ]
        ],
        "claims": [],
        "evidence": [],
        "messages": [],
    }


def claim(data, key, source, target, relation, **extra):
    row = {
        "id": key,
        "source": source,
        "target": target,
        "relation": relation,
        "status": "confirmed",
        "observed_at": RECENT,
        "valid_from": OLD,
        "valid_to": None,
        "evidence_ids": ["e:" + key],
        **extra,
    }
    data["claims"].append(row)
    data["evidence"].append(
        {"id": "e:" + key, "at": RECENT, "text": f"Recorded {relation} from {source} to {target}."}
    )
    return row


def message(data, key, contact="b", at=RECENT, direction="in", **extra):
    data["messages"].append(
        {
            "id": key,
            "contact_id": contact,
            "at": at,
            "channel": "email",
            "direction": direction,
            "direct": True,
            "text": "Actual source message",
            **extra,
        }
    )


def expand(data, **kwargs):
    from adapters.network.scopes import expand_scopes

    query = GraphQuery(focus=kwargs.pop("focus", "a"), expand="1", **kwargs)
    return expand_scopes(data, query, eligible_claims(data, query))


def candidates(result):
    return {row["id"]: row for row in result["candidates"]}


def test_scope_query_defaults_and_canonical_csv():
    assert GraphQuery().scopes == "direct,explicit"
    assert GraphQuery(scopes="organization,direct,project").scopes == "direct,project,organization"
    assert GraphQuery(scopes="").scopes == ""
    for value in ("direct,direct", "neighbours", "direct,", ",project"):
        with pytest.raises(ValidationError):
            GraphQuery(scopes=value)
    for values in (
        {"scope_window": 7},
        {"scope_sort": "score"},
        {"min_sessions": -1},
        {"min_sessions": 1001},
    ):
        with pytest.raises(ValidationError):
            GraphQuery(**values)


def test_empty_scopes_means_only_focus():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    result = expand(data, scopes="")
    assert result["nodes"] == ["a"]
    assert result["edges"] == result["candidates"] == []


def test_four_scopes_overlap_without_turning_context_into_interaction():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    claim(data, "collab", "a", "b", "Collaborates with")
    for key in ("a", "b"):
        claim(data, key + "p", key, "project", "Project member")
        claim(data, key + "o", key, "org", "Works at")
    message(data, "owner-b")
    row = candidates(expand(data, scopes="direct,explicit,project,organization"))["b"]
    assert row["scopes"] == ["direct", "explicit", "project", "organization"]
    assert {p["scope"] for p in row["paths"]} == set(row["scopes"])
    assert row["interaction"]["sessions"] is None
    assert row["interaction"]["reciprocal_sessions"] is None
    assert row["interaction"]["last_at"] is None
    assert all(
        p["last_event_at"] is None
        for p in row["paths"]
        if p["scope"] in {"project", "organization"}
    )


def test_exact_pair_messages_generate_resolvable_direct_edges_and_sessions():
    data = dataset()
    message(data, "one")
    message(data, "two", at="2026-09-20T10:20:00Z", direction="out")
    message(data, "three", at="2026-09-21T10:00:00Z")
    result = expand(data, focus="owner", scopes="direct", min_sessions=2)
    row = candidates(result)["b"]
    assert row["interaction"]["sessions"] == 2
    assert row["interaction"]["reciprocal_sessions"] == 1
    assert {eid for e in result["edges"] for eid in e["evidence_ids"]} == {"one", "two", "three"}
    assert candidates(expand(data, scopes="direct")) == {}


def test_explicit_paths_use_at_most_one_person_intermediary_without_owner_hub():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    claim(data, "bc", "b", "c", "Introduced")
    claim(data, "cd", "c", "d", "Collaborates with")
    claim(data, "ao", "a", "owner", "In contact")
    claim(data, "od", "owner", "d", "Collaborates with")
    result = expand(data, scopes="explicit", depth=1, min_activity=100)
    rows = candidates(result)
    assert "c" in rows and "d" not in rows
    path = rows["c"]["paths"][0]
    assert path["node_ids"] == ["a", "b", "c"]
    assert path["claim_ids"] == ["ab", "bc"]
    assert "introduction to" not in path["label"].lower()
    assert next(e for e in result["edges"] if e["id"] == "bc")["source"] == "b"


def test_two_contact_legs_do_not_imply_explicit_collaboration():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    claim(data, "bc", "b", "c", "In contact")
    assert not candidates(expand(data, scopes="explicit"))


def test_pending_possible_introduction_never_becomes_completed():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    claim(data, "bc", "b", "c", "Possible introduction", status="pending")
    assert "c" not in candidates(expand(data, scopes="explicit"))
    row = candidates(expand(data, scopes="explicit", include_pending=True))["c"]
    assert row["paths"][0]["status"] == "pending"
    assert "unconfirmed" in row["paths"][0]["label"].lower()


def test_shared_context_retained_through_event_filters_with_unknown_overlap():
    data = dataset()
    claim(data, "ap", "a", "project", "Project member", valid_from=None)
    claim(data, "bp", "b", "project", "Project member", valid_from=None)
    result = expand(data, scopes="project", scope_window=30, min_sessions=50)
    row = candidates(result)["b"]
    assert row["paths"][0]["overlap"] == "unknown"
    assert row["last_event_at"] is None
    assert "overlap unknown" in row["paths"][0]["label"].lower()
    assert candidates(expand(data, focus="project", scopes="project")).keys() == {"a", "b"}


def test_disjoint_project_periods_only_history_and_labelled():
    data = dataset()
    claim(data, "ap", "a", "project", "Project member", valid_to="2026-04-01T00:00:00Z")
    claim(data, "bp", "b", "project", "Project member", valid_from="2026-05-01T00:00:00Z")
    assert not candidates(expand(data, scopes="project"))
    path = candidates(expand(data, scopes="project", mode="history"))["b"]["paths"][0]
    assert path["overlap"] == "different_periods"
    assert "different periods" in path["label"].lower()
    assert path["active"] is False


def test_missing_future_and_empty_sources_cannot_support_paths():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    data["evidence"].clear()
    assert not candidates(expand(data))
    data["evidence"] = [{"id": "e:ab", "at": "2027-01-01T00:00:00Z", "text": "source"}]
    assert not candidates(expand(data))
    data["evidence"][0].update(at=OLD, text="")
    assert not candidates(expand(data))


def test_event_window_uses_source_event_not_recent_import_and_sessions_only_direct():
    data = dataset()
    claim(data, "ab", "a", "b", "Collaborates with")
    data["evidence"][0]["at"] = OLD
    assert "b" not in candidates(expand(data, scopes="explicit", scope_window=30))
    assert "b" in candidates(expand(data, scopes="explicit", min_sessions=100))


def test_direct_session_filter_does_not_remove_other_scope_membership():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    claim(data, "collab", "a", "b", "Collaborates with")
    row = candidates(expand(data, scopes="direct,explicit", min_sessions=1))["b"]
    assert row["scopes"] == ["explicit"]


def test_sorting_is_pair_specific_and_deterministic():
    data = dataset()
    message(data, "b1", at="2026-09-01T10:00:00Z")
    message(data, "b2", at="2026-09-02T10:00:00Z")
    message(data, "c1", contact="c", at=RECENT)
    assert [r["id"] for r in expand(data, focus="owner")["candidates"]] == ["c", "b"]
    assert [r["id"] for r in expand(data, focus="owner", scope_sort="frequency")["candidates"]] == [
        "b",
        "c",
    ]
    assert [r["id"] for r in expand(data, focus="owner", scope_sort="name")["candidates"]] == [
        "b",
        "c",
    ]


def test_bounds_include_complete_path_bundles_and_report_omissions():
    data = dataset()
    for i in range(60):
        key = f"p{i:02}"
        context = f"project{i:02}"
        data["nodes"].extend(
            [
                {"id": key, "name": key, "kind": "person"},
                {"id": context, "name": context, "kind": "project"},
            ]
        )
        claim(data, key + "a", "a", context, "Project member")
        claim(data, key + "b", key, context, "Project member")
    result = expand(data, scopes="project")
    assert len(result["nodes"]) <= 50 and len(result["edges"]) <= 100
    assert result["omitted_counts"]["candidates"] > 0
    assert result["omitted_counts"]["paths"] > 0
    edge_ids = {e["id"] for e in result["edges"]}
    for row in result["candidates"]:
        for path in row["paths"]:
            assert set(path["node_ids"]) <= set(result["nodes"])
            assert set(path["claim_ids"]) <= edge_ids
    assert result["counts"]["project"] == len(result["candidates"])


def test_late_correction_does_not_leak_and_history_retains_source_bundle():
    data = dataset()
    row = claim(
        data,
        "ao",
        "a",
        "org",
        "Works at",
        valid_to="2026-07-01T00:00:00Z",
        end_observed_at="2026-09-20T00:00:00Z",
        correction_evidence_ids=["correction"],
    )
    claim(data, "bo", "b", "org", "Advises")
    for source in data["evidence"]:
        source["at"] = OLD
    for edge in data["claims"]:
        edge["observed_at"] = OLD
    data["evidence"].append(
        {
            "id": "correction",
            "at": "2026-09-20T00:00:00Z",
            "text": "A left the organization in July.",
        }
    )
    early = expand(data, scopes="organization", as_of="2026-08-01T00:00:00Z")
    early_path = candidates(early)["b"]["paths"][0]
    assert "correction" not in early_path["evidence_ids"]
    assert early_path["active"] is True
    assert not candidates(expand(data, scopes="organization"))
    history = expand(data, scopes="organization", mode="history")
    later_path = candidates(history)["b"]["paths"][0]
    assert "correction" in later_path["evidence_ids"]
    assert later_path["active"] is False
    assert row["correction_evidence_ids"] == ["correction"]


def test_source_knowledge_and_claim_review_cutoffs_both_apply():
    data = dataset()
    row = claim(data, "ab", "a", "b", "Collaborates with")
    data["evidence"][0]["known_at"] = "2027-01-01T00:00:00Z"
    assert not candidates(expand(data))
    del data["evidence"][0]["known_at"]
    row["observed_at"] = "2027-01-01T00:00:00Z"
    assert not candidates(expand(data))
    row["observed_at"] = OLD
    row["status"] = "rejected"
    assert not candidates(expand(data, include_pending=True))


def test_explicit_participant_pair_never_reuses_unrelated_owner_contact():
    data = dataset()
    message(data, "ab", participant_ids=["a", "b"])
    message(data, "owner-b")
    row = candidates(expand(data, scopes="direct"))["b"]
    assert row["interaction"]["sessions"] == 1
    assert row["paths"][0]["evidence_ids"] == ["ab"]
    assert row["interaction"]["reciprocal_sessions"] == 0


def test_context_recency_sort_does_not_borrow_owner_message_dates():
    data = dataset()
    for person in ("a", "b", "c"):
        claim(data, person + "o", person, "org", "Works at")
    message(data, "owner-c", contact="c")
    result = expand(data, scopes="organization", scope_sort="recent")
    assert [c["id"] for c in result["candidates"]] == ["b", "c"]
    assert all(c["last_event_at"] is None for c in result["candidates"])


def test_edge_limit_never_cuts_candidate_scope_representatives():
    data = dataset()
    for i in range(130):
        claim(data, f"contact{i:03}", "a", "b", "In contact")
    claim(data, "collab", "a", "b", "Collaborates with")
    for key in ("a", "b"):
        claim(data, key + "p", key, "project", "Project member")
        claim(data, key + "o", key, "org", "Works at")
    result = expand(data, scopes="direct,explicit,project,organization")
    assert len(result["edges"]) == 100
    assert result["omitted_counts"]["edges"] == 35
    assert result["omitted_counts"]["paths"] > 0
    row = candidates(result)["b"]
    assert row["scopes"] == ["direct", "explicit", "project", "organization"]
    for path in row["paths"]:
        assert set(path["claim_ids"]) <= {edge["id"] for edge in result["edges"]}


def test_unknown_dates_are_not_silently_disjoint_and_affiliation_direction_is_preserved():
    data = dataset()
    claim(data, "ao", "a", "org", "Advises", valid_from=None)
    claim(data, "bo", "b", "org", "Works at")
    result = expand(data, scopes="organization")
    assert candidates(result)["b"]["paths"][0]["overlap"] == "unknown"
    assert {edge["relation"] for edge in result["edges"]} == {"Advises", "Works at"}
    assert all(edge["target"] == "org" for edge in result["edges"])
    assert candidates(expand(data, focus="org", scopes="organization")).keys() == {"a", "b"}


def test_typed_person_roles_do_not_automatically_establish_direct_contact():
    for relation in ("Collaborates with", "Introduced", "Client of", "Reports to"):
        data = dataset()
        claim(data, "ab", "a", "b", relation)
        assert not candidates(expand(data, scopes="direct")), relation


def test_late_correction_does_not_refresh_old_collaboration_event():
    data = dataset()
    claim(
        data,
        "ab",
        "a",
        "b",
        "Collaborates with",
        valid_to="2026-06-01T00:00:00Z",
        end_observed_at=RECENT,
        correction_evidence_ids=["correction"],
    )
    data["evidence"][0]["at"] = OLD
    data["evidence"].append(
        {"id": "correction", "at": RECENT, "text": "Their collaboration ended in June."}
    )
    result = expand(data, scopes="explicit", mode="history", scope_window=30)
    assert not candidates(result)


def test_source_observed_at_is_a_separate_knowledge_cutoff():
    data = dataset()
    claim(data, "ab", "a", "b", "In contact")
    data["evidence"][0]["observed_at"] = "2027-01-01T00:00:00Z"
    assert not candidates(expand(data))
