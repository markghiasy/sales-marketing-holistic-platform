from datetime import UTC, datetime
from itertools import combinations, pairwise

import pytest

from adapters.reply_signal import reply_signal
from tests.test_reply_signal import _make_identity, _make_message, _make_thread


def edge(cur, a, b, status="pending", method="outlook_same_channel_dedupe"):
    cur.execute(
        """insert into link_candidate
        (identity_a_id,identity_b_id,method,status,score,reason)
        values (%s,%s,%s,%s,0.6,'same normalized name') returning id""",
        (a, b, method, status),
    )
    return str(cur.fetchone()[0])


def identities(cur, n):
    return [_make_identity(cur, "outlook", f"p{x}@example.test") for x in range(n)]


def test_pair_aggregates_without_merging_and_deduplicates_messages(db_conn):
    cur = db_conn.cursor()
    a, b, me = identities(cur, 3)
    cur.execute("update identity set is_self=true where id=%s", (me,))
    edge(cur, a, b)
    t = _make_thread(cur, "outlook")
    now = datetime.now(UTC)
    _make_message(cur, t, "outlook", "inbound", b, [a, b, me], now)
    _make_message(cur, t, "outlook", "outbound", me, [a, b, me], now)
    signal = reply_signal(cur, a)
    assert (signal.sent_count, signal.received_count) == (1, 1)
    assert signal.provisional is True
    assert signal.identity_count == 2
    cur.execute("select count(*) from person")
    assert cur.fetchone()[0] == 0
    cur.execute("select count(*) from merge_log")
    assert cur.fetchone()[0] == 0


@pytest.mark.parametrize(
    "n,edge_count,allowed,reason",
    [
        (8, 14, True, "eligible"),
        (8, 13, False, "sparse"),
        (9, 36, False, "too_large"),
    ],
)
def test_size_and_density_boundaries(db_conn, n, edge_count, allowed, reason):
    from adapters.resolution.clusters import candidate_cluster

    cur = db_conn.cursor()
    ids = identities(cur, n)
    pairs = list(combinations(ids, 2))
    # Star first ensures every identity is reachable at both density boundaries.
    for a, b in pairs[:edge_count]:
        edge(cur, a, b)
    result = candidate_cluster(cur, ids[0])
    assert result.allowed is allowed
    assert result.reason == reason
    assert bool(result.suggestions)


def test_duplicate_edges_do_not_inflate_density_and_rejection_blocks_transitivity(db_conn):
    from adapters.resolution.clusters import candidate_cluster

    cur = db_conn.cursor()
    a, b, c, d = identities(cur, 4)
    edge(cur, a, b)
    edge(cur, b, c)
    edge(cur, c, d)
    assert candidate_cluster(cur, a).allowed
    edge(cur, b, a)
    edge(cur, a, b, method="contact_bridge")
    assert candidate_cluster(cur, a).density == 0.5
    edge(cur, a, c, status="rejected")
    assert candidate_cluster(cur, a).reason == "rejected_pair"


def test_rejected_retired_self_and_hidden_edges_are_not_members(db_conn):
    from adapters.resolution.clusters import candidate_cluster

    cur = db_conn.cursor()
    ids = identities(cur, 6)
    edge(cur, ids[0], ids[1], status="retired")
    edge(cur, ids[0], ids[2], method="email_signature_phone")
    edge(cur, ids[0], ids[3], status="rejected")
    edge(cur, ids[0], ids[4])
    edge(cur, ids[0], ids[5])
    cur.execute("update identity set is_self=true where id=%s", (ids[4],))
    cur.execute("insert into contact_hidden(contact_key) values (%s)", (ids[5],))
    result = candidate_cluster(cur, ids[0])
    assert result.member_ids == [ids[0]]
    assert not result.suggestions


def test_sparse_component_falls_back_to_own_counts(db_conn):
    from adapters.resolution.clusters import candidate_cluster

    cur = db_conn.cursor()
    ids = identities(cur, 5)
    for a, b in pairwise(ids):
        edge(cur, a, b)
    t = _make_thread(cur, "outlook")
    _make_message(cur, t, "outlook", "inbound", ids[0], [ids[0]], datetime.now(UTC))
    signal = reply_signal(cur, ids[0])
    assert signal.received_count == 1
    assert not signal.provisional
    assert candidate_cluster(cur, ids[0]).reason == "sparse"


def test_confirmed_group_included_and_candidate_status_changes_take_effect(db_conn):
    from adapters.resolution.clusters import candidate_cluster
    from adapters.resolution.merge import apply_merge

    cur = db_conn.cursor()
    a, b, c = identities(cur, 3)
    key = apply_merge(cur, a, b, method="manual_link", decision_kind="manual")
    cid = edge(cur, b, c)
    result = candidate_cluster(cur, str(key))
    assert set(result.member_ids) == {a, b, c}
    assert result.allowed
    cur.execute("update link_candidate set status='rejected' where id=%s", (cid,))
    assert set(candidate_cluster(cur, a).member_ids) == {a, b}
