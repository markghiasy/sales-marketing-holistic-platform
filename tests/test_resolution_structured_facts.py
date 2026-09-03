from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.structured_facts import extract_structured_facts


def _make_linkedin_connection(cur, first_name: str = "Eric", last_name: str = "Tham", company: str | None = None, position: str | None = None) -> str:
    conn_id = f"https://linkedin.com/in/{uuid.uuid4().hex[:10]}"
    cur.execute(
        "insert into linkedin_connection (id, first_name, last_name, company, position) values (%s, %s, %s, %s, %s)",
        (conn_id, first_name, last_name, company, position),
    )
    return conn_id


class TestExtractStructuredFacts:
    def test_company_produces_a_works_at_fact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        conn_id = _make_linkedin_connection(cur, company="Acme Inc")

        count = extract_structured_facts(cur)

        assert count >= 1
        cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        identity_id = cur.fetchone()[0]
        cur.execute(
            "select fact_type, object_org_id, confidence, status, source from fact where subject_identity_id = %s and fact_type = 'works_at'",
            (identity_id,),
        )
        fact_type, org_id, confidence, status, source = cur.fetchone()
        assert fact_type == "works_at"
        assert org_id is not None
        assert confidence == 1.0
        assert status == "confirmed"  # structured-source facts are high-confidence, not a guess
        assert source == "linkedin_connection"

    def test_position_produces_a_has_title_fact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        conn_id = _make_linkedin_connection(cur, position="Data Lead")

        extract_structured_facts(cur)

        cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        identity_id = cur.fetchone()[0]
        cur.execute(
            "select object_text from fact where subject_identity_id = %s and fact_type = 'has_title'",
            (identity_id,),
        )
        assert cur.fetchone()[0] == "Data Lead"

    def test_missing_company_and_position_produce_no_facts(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_linkedin_connection(cur, company=None, position=None)

        count = extract_structured_facts(cur)

        assert count == 0

    def test_rerun_does_not_duplicate_facts(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_linkedin_connection(cur, company="Acme Inc")

        first_count = extract_structured_facts(cur)
        second_count = extract_structured_facts(cur)

        assert first_count == 1
        assert second_count == 0

    def test_company_variant_reuses_the_same_organization(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_linkedin_connection(cur, first_name="Eric", last_name="Tham", company="Acme Inc")
        _make_linkedin_connection(cur, first_name="Sarah", last_name="Chen", company="Acme")

        extract_structured_facts(cur)

        cur.execute("select object_org_id from fact where fact_type = 'works_at'")
        org_ids = {row[0] for row in cur.fetchall()}
        assert len(org_ids) == 1


class TestExtractStructuredFactsBackfill:
    def test_sets_display_name_from_connection_name(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        conn_id = _make_linkedin_connection(cur, first_name="Eric", last_name="Tham", company="Acme")

        extract_structured_facts(cur)

        cur.execute("select display_name from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        assert cur.fetchone()[0] == "Eric Tham"
