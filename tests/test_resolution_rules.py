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


from adapters.resolution.rules import rule_signature_phone


def _make_message(cur, thread_id: str, from_identity_id: str, body_text: str, direction: str = "outbound") -> str:
    cur.execute(
        """
        insert into message (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, raw)
        values (%s, 'outlook', %s, %s, now(), %s, %s, '{}')
        returning id
        """,
        (thread_id, f"msg-{uuid.uuid4().hex}", direction, from_identity_id, body_text),
    )
    return str(cur.fetchone()[0])


def _make_thread(cur) -> str:
    cur.execute(
        "insert into thread (channel, external_id) values ('outlook', %s) returning id",
        (f"thread-{uuid.uuid4().hex}",),
    )
    return str(cur.fetchone()[0])


class TestRuleSignaturePhone:
    def test_phone_in_signature_queues_a_high_score_candidate(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Eric Tham")
        thread = _make_thread(cur)
        body = f"Thanks,\nEric Tham\nMobile: {digits}"
        _make_message(cur, thread, outlook_id, body, direction="outbound")

        # not asserting an exact `count` here: this local database carries
        # real committed rows alongside whatever this test inserts (see
        # conftest.py's db_conn fixture note), so the rule may legitimately
        # find other matches too. Scope assertions to this test's own
        # identity pair instead.
        rule_signature_phone(cur)

        cur.execute(
            "select status, score, method from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )
        status, score, method = cur.fetchone()
        assert status == "pending"
        assert score == 0.8
        assert method == "email_signature_phone"

    def test_inbound_messages_are_also_scanned(self, db_conn: psycopg.Connection):
        # a phone number in the SENDER's signature is exactly as valid
        # evidence on an inbound message as an outbound one — the mailbox
        # owner's own outbound signature was never a requirement, just
        # the first case built. from_identity_id on an inbound message is
        # whoever sent it, so this links their Outlook identity to their
        # own WhatsApp number, same mechanism, just the other direction.
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        wa_id = _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Eric Tham")
        thread = _make_thread(cur)
        body = f"Thanks,\nEric Tham\nMobile: {digits}"
        _make_message(cur, thread, outlook_id, body, direction="inbound")

        rule_signature_phone(cur)

        cur.execute(
            "select status, score, method from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (wa_id, wa_id),
        )
        status, score, method = cur.fetchone()
        assert status == "pending"
        assert score == 0.8
        assert method == "email_signature_phone"

    def test_number_outside_the_last_few_lines_is_not_matched(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        wa_id = _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Someone Else")
        thread = _make_thread(cur)
        padding = "\n".join(f"line {n}" for n in range(20))
        body = f"By the way my number is {digits}\n{padding}\nThanks,\nEric"
        _make_message(cur, thread, outlook_id, body, direction="outbound")

        rule_signature_phone(cur)

        cur.execute(
            "select count(*) from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (wa_id, wa_id),
        )
        assert cur.fetchone()[0] == 0


class TestRuleExactEmailMatchBackfill:
    def test_backfills_display_name_on_a_previously_nameless_linkedin_identity(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        # simulate extract_structured_facts having created this identity
        # first, with no display_name — handle must be the linkedin_connection's
        # id (a profile URL), not the email, since that's what the rule
        # actually keys the linkedin identity's handle on
        conn_id = _make_linkedin_connection(cur, email=email, first_name="Eric", last_name="Tham")
        cur.execute("insert into identity (channel, handle) values ('linkedin', %s)", (conn_id,))
        outlook_id = _make_identity(cur, "outlook", email, "Sarah Chen")

        rule_exact_email_match(cur)

        cur.execute("select display_name from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        assert cur.fetchone()[0] == "Eric Tham"
        # and now that the name is backfilled, the contradiction check
        # actually fires — the whole point of the fix
        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        assert cur.fetchone()[0] is None

    def test_does_not_overwrite_an_existing_display_name(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        conn_id = _make_linkedin_connection(cur, email=email, first_name="Different", last_name="Person")
        cur.execute("insert into identity (channel, handle, display_name) values ('linkedin', %s, 'Original Name')", (conn_id,))
        _make_identity(cur, "outlook", email, "Original Name")

        rule_exact_email_match(cur)

        cur.execute("select display_name from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        assert cur.fetchone()[0] == "Original Name"


class TestRuleContactBridgeGenericEmail:
    def test_generic_role_email_does_not_auto_confirm_the_bridge(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        digits = "1580" + str(uuid.uuid4().int)[:6]
        outlook_id = _make_identity(cur, "outlook", "support@acme.com", "Eric Tham")
        wa_id = _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Eric Tham")
        _make_graph_contact(cur, emails=["support@acme.com"], phones=[digits], display_name="Eric Tham")

        rule_contact_bridge(cur)

        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        assert cur.fetchone()[0] is None
        cur.execute("select status from link_candidate where identity_a_id = %s or identity_b_id = %s", (wa_id, wa_id))
        assert cur.fetchone()[0] == "pending"


class TestTransitiveOverMerge:
    def test_a_b_c_chain_does_not_over_merge_through_an_unnamed_bridge(self, db_conn: psycopg.Connection):
        # the design doc's own adversarial case: A-B auto-confirms (B has
        # no contradicting name to catch), then B-C is proposed — this
        # must now be blocked, not silently auto-confirmed, because C's
        # name contradicts A's, which is already in B's cluster
        cur = db_conn.cursor()
        email_a = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        _make_identity(cur, "outlook", email_a, "Eric Tham")
        # this LinkedIn connection has no name at all (first_name/last_name
        # both None), so rule_exact_email_match's own display_name
        # backfill (fix 12.1) leaves the resulting identity nameless too
        conn_a = _make_linkedin_connection(cur, email=email_a, first_name=None, last_name=None)
        rule_exact_email_match(cur)
        cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (conn_a,))
        b = str(cur.fetchone()[0])

        email_c = f"sarah-{uuid.uuid4().hex[:8]}@example.com"
        c = _make_identity(cur, "outlook", email_c, "Sarah Chen")
        _make_linkedin_connection(cur, email=email_c, first_name="Sarah", last_name="Chen")
        # propose b (LinkedIn identity, now part of a's cluster) against
        # a fresh contact bridge to c — reuse rule_exact_email_match's
        # own mechanism isn't a fit here since b isn't a fresh LinkedIn
        # connection; call the shared merge proposer directly instead,
        # simulating whatever rule would have proposed b+c
        from adapters.resolution.rules import _propose_and_maybe_confirm
        _propose_and_maybe_confirm(cur, b, c, "test_transitive", "test", None)

        cur.execute("select person_id from identity where id = %s", (c,))
        assert cur.fetchone()[0] is None
        cur.execute("select status from link_candidate where identity_a_id = %s or identity_b_id = %s", (c, c))
        assert cur.fetchone()[0] == "pending"


class TestRerunDoesNotDuplicate:
    def test_running_rule_exact_email_match_twice_does_not_duplicate(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        email = f"eric-{uuid.uuid4().hex[:8]}@example.com"
        _make_identity(cur, "outlook", email, "Eric Tham")
        _make_linkedin_connection(cur, email=email, first_name="Eric", last_name="Tham")

        first_count = rule_exact_email_match(cur)
        second_count = rule_exact_email_match(cur)

        assert first_count == 1
        assert second_count == 0
        cur.execute("select count(*) from link_candidate where method = 'exact_email'")
        assert cur.fetchone()[0] == 1
