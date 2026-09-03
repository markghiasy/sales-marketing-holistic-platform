from __future__ import annotations

from adapters.resolution.naming import select_names


def test_picks_longest_name_like_candidate_as_primary():
    primary, preferred = select_names(["Eric Tham", "Eric"])
    assert primary == "Eric Tham"
    assert preferred == "Eric"


def test_no_preferred_name_when_only_one_candidate():
    primary, preferred = select_names(["Eric Tham"])
    assert primary == "Eric Tham"
    assert preferred is None


def test_no_preferred_name_when_all_candidates_identical():
    primary, preferred = select_names(["Eric Tham", "Eric Tham"])
    assert primary == "Eric Tham"
    assert preferred is None


def test_filters_out_handle_like_candidates():
    # a single lowercase word with no space looks like a username, not a
    # real name, and should be excluded from consideration entirely
    primary, preferred = select_names(["Eric Tham", "eric_t99"])
    assert primary == "Eric Tham"
    assert preferred is None


def test_falls_back_to_first_candidate_when_nothing_looks_name_like():
    primary, preferred = select_names(["eric_t99", "12345"])
    assert primary == "eric_t99"
    assert preferred is None


def test_ignores_none_and_empty_candidates():
    primary, preferred = select_names(["Eric Tham", None, "", "Eric"])
    assert primary == "Eric Tham"
    assert preferred == "Eric"


def test_all_none_or_empty_candidates_falls_back_gracefully():
    # a merge always involves at least one real identity row, but that
    # identity may have no display_name at all (e.g. a WhatsApp contact
    # with no push name) — apply_merge must not crash in that case
    primary, preferred = select_names([None, "", None])
    assert primary == ""
    assert preferred is None


def test_truly_empty_list_falls_back_gracefully():
    primary, preferred = select_names([])
    assert primary == ""
    assert preferred is None
