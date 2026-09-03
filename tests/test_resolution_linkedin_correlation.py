from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.linkedin_correlation import rule_linkedin_correlation


def _make_identity(cur, channel: str, handle: str, display_name: str | None = None) -> str:
    cur.execute(
        "insert into identity (channel, handle, display_name) values (%s, %s, %s) returning id",
        (channel, handle, display_name),
    )
    return str(cur.fetchone()[0])


def _make_linkedin_connection(cur, first_name: str, last_name: str, company: str | None = None) -> str:
    conn_id = f"https://linkedin.com/in/{uuid.uuid4().hex[:10]}"
    cur.execute(
        "insert into linkedin_connection (id, first_name, last_name, company) values (%s, %s, %s, %s)",
        (conn_id, first_name, last_name, company),
    )
    return conn_id


class TestRuleLinkedinCorrelation:
    def test_exact_name_match_queues_a_candidate_never_confirmed(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")

        count = rule_linkedin_correlation(cur)

        assert count == 1
        cur.execute(
            "select status, method, score from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )
        status, method, _score = cur.fetchone()
        assert status == "pending"
        assert method == "linkedin_name_company"
        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        assert cur.fetchone()[0] is None

    def test_no_match_for_unrelated_names(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_identity(cur, "outlook", f"sarah-{uuid.uuid4().hex[:8]}@example.com", "Sarah Chen")
        _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")

        count = rule_linkedin_correlation(cur)

        assert count == 0

    def test_score_is_always_below_rule4s_band(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")

        rule_linkedin_correlation(cur)

        cur.execute(
            "select score from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )
        assert cur.fetchone()[0] < 0.8  # Rule 4's fixed score

    def test_rejected_pair_is_not_re_proposed(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")
        rule_linkedin_correlation(cur)
        cur.execute(
            "update link_candidate set status = 'rejected' where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )

        count = rule_linkedin_correlation(cur)

        assert count == 0
