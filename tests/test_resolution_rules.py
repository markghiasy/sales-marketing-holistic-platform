# tests/test_resolution_rules.py
from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.rules import (
    rule_contact_bridge,
    rule_exact_email_match,
)


def _make_identity(cur, channel: str, handle: str, display_name: str | None = None) -> str:
    cur.execute(
        "insert into identity (channel, handle, display_name) values (%s, %s, %s) returning id",
        (channel, handle, display_name),
    )
    return str(cur.fetchone()[0])


def _make_linkedin_connection(cur, email: str | None = None, first_name: str = "Test", last_name: str = "Person", company: str | None = None) -> str:
    conn_id = f"https://linkedin.com/in/{uuid.uuid4().hex[:10]}"
    cur.execute(
        """
        insert into linkedin_connection (id, first_name, last_name, email, company)
        values (%s, %s, %s, %s, %s)
        """,
        (conn_id, first_name, last_name, email, company),
    )
    return conn_id


def _make_graph_contact(cur, emails: list[str] | None = None, phones: list[str] | None = None, display_name: str | None = None) -> str:
    contact_id = f"contact-{uuid.uuid4().hex[:10]}"
    cur.execute(
        "insert into graph_contact (id, display_name, emails, phones) values (%s, %s, %s, %s)",
        (contact_id, display_name, emails or [], phones or []),
    )
    return contact_id


class TestRuleExactEmailMatch:
    def test_matching_email_auto_confirms_the_merge(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        outlook_id = _make_identity(cur, "outlook", email, "Eric Tham")
        _make_linkedin_connection(cur, email=email, first_name="Eric", last_name="Tham")

        count = rule_exact_email_match(cur)

        assert count == 1
        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        assert cur.fetchone()[0] is not None
        cur.execute("select status, method from link_candidate where identity_a_id = %s or identity_b_id = %s", (outlook_id, outlook_id))
        status, method = cur.fetchone()
        assert status == "confirmed"
        assert method == "exact_email"

    def test_generic_role_email_does_not_auto_confirm(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"support-{uuid.uuid4().hex[:8]}@acme.com".replace(f"support-{uuid.uuid4().hex[:8]}", "support")
        outlook_id = _make_identity(cur, "outlook", "support@acme.com", None)
        _make_linkedin_connection(cur, email="support@acme.com")

        rule_exact_email_match(cur)

        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        assert cur.fetchone()[0] is None
        cur.execute("select status from link_candidate where identity_a_id = %s or identity_b_id = %s", (outlook_id, outlook_id))
        assert cur.fetchone()[0] == "pending"

    def test_contradicting_display_names_block_auto_confirm(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"shared-{uuid.uuid4().hex[:8]}@example.com"
        outlook_id = _make_identity(cur, "outlook", email, "Sarah Chen")
        _make_linkedin_connection(cur, email=email, first_name="Eric", last_name="Tham")

        rule_exact_email_match(cur)

        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        assert cur.fetchone()[0] is None
        cur.execute("select status from link_candidate where identity_a_id = %s or identity_b_id = %s", (outlook_id, outlook_id))
        assert cur.fetchone()[0] == "pending"

    def test_rejected_pair_is_not_re_proposed(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        outlook_id = _make_identity(cur, "outlook", email, "Eric Tham")
        conn_id = _make_linkedin_connection(cur, email=email, first_name="Eric", last_name="Tham")
        cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        # the rule creates the linkedin identity itself on first run; simulate
        # a prior rejection by running once, rejecting, then re-running
        rule_exact_email_match(cur)
        cur.execute("update link_candidate set status = 'rejected' where identity_a_id = %s or identity_b_id = %s", (outlook_id, outlook_id))
        cur.execute("update identity set person_id = null where id = %s", (outlook_id,))

        count = rule_exact_email_match(cur)

        assert count == 0


class TestRuleContactBridge:
    def test_contact_with_both_email_and_phone_bridges_two_identities(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        outlook_id = _make_identity(cur, "outlook", email, "Eric Tham")
        wa_id = _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Eric Tham")
        _make_graph_contact(cur, emails=[email], phones=[digits], display_name="Eric Tham")

        count = rule_contact_bridge(cur)

        assert count == 1
        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        (person_a,) = cur.fetchone()
        cur.execute("select person_id from identity where id = %s", (wa_id,))
        (person_b,) = cur.fetchone()
        assert person_a is not None
        assert person_a == person_b

    def test_group_chat_jids_are_skipped_as_the_phone_side(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        _make_identity(cur, "outlook", email, "Eric Tham")
        _make_identity(cur, "whatsapp", f"{digits}@g.us", "Some Group")
        _make_graph_contact(cur, emails=[email], phones=[digits], display_name="Eric Tham")

        count = rule_contact_bridge(cur)

        assert count == 0

    def test_recycled_number_with_contradicting_name_does_not_auto_confirm(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        outlook_id = _make_identity(cur, "outlook", email, "Eric Tham")
        wa_id = _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Sarah Chen")
        _make_graph_contact(cur, emails=[email], phones=[digits], display_name="Eric Tham")

        rule_contact_bridge(cur)

        cur.execute("select status from link_candidate where identity_a_id = %s or identity_b_id = %s", (outlook_id, outlook_id))
        assert cur.fetchone()[0] == "pending"
        cur.execute("select person_id from identity where id = %s", (wa_id,))
        assert cur.fetchone()[0] is None

    def test_contact_with_only_email_does_not_bridge(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        _make_identity(cur, "outlook", email, "Eric Tham")
        _make_graph_contact(cur, emails=[email], phones=[], display_name="Eric Tham")

        count = rule_contact_bridge(cur)

        assert count == 0
