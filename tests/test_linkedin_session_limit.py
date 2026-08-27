from __future__ import annotations

import json

import pytest

from adapters.linkedin import session_limit


@pytest.fixture(autouse=True)
def isolated_state_path(tmp_path, monkeypatch):
    # every test gets its own state file — never touches the real one
    # tracking today's actual LinkedIn session count
    monkeypatch.setattr(session_limit, "STATE_PATH", tmp_path / ".session_count.json")


def test_allows_sessions_up_to_the_cap():
    for _ in range(4):
        session_limit.record_session(max_sessions_per_day=4)  # should not raise


def test_blocks_the_session_after_the_cap():
    for _ in range(4):
        session_limit.record_session(max_sessions_per_day=4)
    with pytest.raises(session_limit.SessionLimitExceeded):
        session_limit.record_session(max_sessions_per_day=4)


def test_blocked_message_names_the_actual_limit():
    for _ in range(4):
        session_limit.record_session(max_sessions_per_day=4)
    with pytest.raises(session_limit.SessionLimitExceeded, match="4/4"):
        session_limit.record_session(max_sessions_per_day=4)


def test_new_day_resets_the_count():
    session_limit.STATE_PATH.write_text(json.dumps({"date": "2020-01-01", "count": 4}))
    session_limit.record_session(max_sessions_per_day=4)  # different date — should not raise
    state = json.loads(session_limit.STATE_PATH.read_text())
    assert state["count"] == 1


def test_repeated_calls_past_the_cap_stay_cheap_and_consistent():
    # a scheduler stuck in a tight retry loop past the cap should get the
    # same clean refusal every time, not an escalating or inconsistent error
    for _ in range(4):
        session_limit.record_session(max_sessions_per_day=4)
    for _ in range(3):
        with pytest.raises(session_limit.SessionLimitExceeded):
            session_limit.record_session(max_sessions_per_day=4)
