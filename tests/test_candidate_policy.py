from pathlib import Path

import pytest

from adapters.resolution.merge import apply_merge
from tests.test_resolution_rules import _make_identity


def test_merge_entrypoint_rejects_automatic_heuristics_before_writing(db_conn):
    cur = db_conn.cursor()
    a = _make_identity(cur, "outlook", "a@example.test")
    b = _make_identity(cur, "whatsapp", "123456789@s.whatsapp.net")
    with pytest.raises(ValueError, match="exact_email"):
        apply_merge(cur, a, b, method="contact_bridge", decision_kind="automatic")
    cur.execute("select count(*) from merge_log")
    assert cur.fetchone()[0] == 0


def test_signature_retirement_is_surgical_and_idempotent(db_conn):
    cur = db_conn.cursor()
    a = _make_identity(cur, "outlook", "a@example.test")
    b = _make_identity(cur, "whatsapp", "123456789@s.whatsapp.net")
    for status in ("pending", "confirmed", "rejected"):
        cur.execute(
            """insert into link_candidate
            (identity_a_id, identity_b_id, method, status, score, reason)
            values (%s,%s,'email_signature_phone',%s,0.8,'original evidence')""",
            (a, b, status),
        )
    migration = Path("db/migrations/0013_retire_email_signature_phone.sql").read_text()
    cur.execute(migration)
    cur.execute(migration)
    cur.execute("select status, reason from link_candidate order by status")
    rows = cur.fetchall()
    assert [r[0] for r in rows] == ["confirmed", "rejected", "retired"]
    assert rows[0][1] == rows[1][1] == "original evidence"
    assert rows[2][1].count("Rule retired") == 1
