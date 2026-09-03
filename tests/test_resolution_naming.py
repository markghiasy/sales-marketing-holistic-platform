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


def test_empty_input_raises():
    import pytest
    with pytest.raises(ValueError):
        select_names([])
