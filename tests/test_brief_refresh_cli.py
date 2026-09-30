import pytest

from tests.test_cluster_briefs import client, seed


def test_stale_refresh_selects_only_stale_visible_contacts(db_conn):
    from adapters.ai_brief import generate_brief
    from scripts.refresh_identity_briefs import stale_keys
    cur = db_conn.cursor()
    a, _b, _t, cid = seed(cur)
    generate_brief(cur, a, client=client())
    assert stale_keys(cur, 10) == set()
    cur.execute("update link_candidate set status='rejected' where id=%s", (cid,))
    assert stale_keys(cur, 1) == {a}
    cur.execute("insert into contact_hidden(contact_key) values (%s)", (a,))
    assert stale_keys(cur, 10) == set()


def test_refresh_cli_rejects_unbounded_or_nonpositive_batch():
    from scripts.refresh_identity_briefs import parse_args
    assert not parse_args([]).apply
    assert parse_args([]).limit == 25
    for limit in ('0', '-1', '501'):
        with pytest.raises(SystemExit):
            parse_args(['--limit', limit])
