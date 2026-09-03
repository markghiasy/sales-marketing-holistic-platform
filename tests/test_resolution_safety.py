# tests/test_resolution_safety.py
from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.safety import (
    MAX_CLUSTER_SIZE,
    cluster_names_contradict,
    cluster_size_after_merge,
    has_existing_candidate,
    is_generic_role_email,
    names_contradict,
)


def _make_identity(cur, channel: str, handle: str, display_name: str | None = None, person_id: str | None = None) -> str:
    cur.execute(
        """
        insert into identity (channel, handle, display_name, person_id)
        values (%s, %s, %s, %s)
        returning id
        """,
        (channel, handle, display_name, person_id),
    )
    return str(cur.fetchone()[0])


def _make_person(cur, primary_name: str = "Test Person") -> str:
    cur.execute("insert into person (primary_name) values (%s) returning id", (primary_name,))
    return str(cur.fetchone()[0])


class TestIsGenericRoleEmail:
    def test_role_address_is_generic(self):
        assert is_generic_role_email("support@acme.com") is True
        assert is_generic_role_email("Sales@Acme.com") is True

    def test_personal_address_is_not_generic(self):
        assert is_generic_role_email("eric.tham@acme.com") is False


class TestClusterSizeAfterMerge:
    def test_two_unresolved_identities_form_a_cluster_of_two(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net")

        assert cluster_size_after_merge(cur, a, b) == 2

    def test_merging_into_an_existing_cluster_counts_the_whole_cluster(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        person = _make_person(cur)
        _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", person_id=person)
        _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", person_id=person)
        existing_third = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", person_id=person)
        new_identity = _make_identity(cur, "outlook", f"new-{uuid.uuid4().hex}@example.com")

        # existing_third is one of the 3 identities already in the cluster;
        # merging new_identity in should count all 3 existing + the new one = 4
        assert cluster_size_after_merge(cur, existing_third, new_identity) == 4

    def test_implausible_cluster_exceeds_max(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        person = _make_person(cur)
        identities = [
            _make_identity(cur, "outlook", f"shared-{uuid.uuid4().hex}@example.com", person_id=person)
            for _ in range(MAX_CLUSTER_SIZE)
        ]
        new_identity = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net")

        result = cluster_size_after_merge(cur, identities[0], new_identity)
        assert result > MAX_CLUSTER_SIZE


class TestHasExistingCandidate:
    def test_no_candidate_returns_false(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net")

        assert has_existing_candidate(cur, a, b) is False

    def test_rejected_candidate_found_regardless_of_pair_order(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net")
        cur.execute(
            """
            insert into link_candidate (identity_a_id, identity_b_id, score, method, status)
            values (%s, %s, 0.5, 'test', 'rejected')
            """,
            (a, b),
        )

        assert has_existing_candidate(cur, a, b) is True
        assert has_existing_candidate(cur, b, a) is True  # order-independent

    def test_pending_candidate_also_counts_now(self, db_conn: psycopg.Connection):
        # this is the behavior change from the old
        # has_existing_rejected_candidate: a pending row from a previous
        # run must also block re-proposing, or every rerun duplicates
        # the human's review queue forever
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net")
        cur.execute(
            """
            insert into link_candidate (identity_a_id, identity_b_id, score, method, status)
            values (%s, %s, 0.5, 'test', 'pending')
            """,
            (a, b),
        )

        assert has_existing_candidate(cur, a, b) is True

    def test_confirmed_candidate_also_counts(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net")
        cur.execute(
            """
            insert into link_candidate (identity_a_id, identity_b_id, score, method, status)
            values (%s, %s, 0.5, 'test', 'confirmed')
            """,
            (a, b),
        )

        assert has_existing_candidate(cur, a, b) is True


class TestNamesContradict:
    def test_clearly_different_names_contradict(self):
        assert names_contradict("Eric Tham", "Sarah Chen") is True

    def test_same_name_does_not_contradict(self):
        assert names_contradict("Eric Tham", "Eric Tham") is False

    def test_formatting_difference_does_not_contradict(self):
        assert names_contradict("Eric Tham", "eric tham") is False

    def test_shared_first_name_does_not_contradict(self):
        # "Eric" alone vs "Eric Tham" share a token — not treated as a
        # contradiction, since one side might just be a shorter display name
        assert names_contradict("Eric Tham", "Eric") is False

    def test_missing_name_never_contradicts(self):
        assert names_contradict(None, "Eric Tham") is False
        assert names_contradict(None, None) is False


class TestClusterNamesContradict:
    def test_contradicts_transitively_through_an_unnamed_bridge(self, db_conn: psycopg.Connection):
        # A ("Eric Tham") and B (unnamed) are already merged into one
        # person; proposing B + C ("Sarah Chen") must still catch the
        # A/C contradiction even though B itself has no name to compare
        cur = db_conn.cursor()
        person = _make_person(cur)
        _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=person)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", None, person_id=person)
        c = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", "Sarah Chen")

        assert cluster_names_contradict(cur, b, c) is True

    def test_does_not_contradict_when_clusters_are_consistent(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        person = _make_person(cur)
        _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=person)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", None, person_id=person)
        c = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", "Eric Tham")

        assert cluster_names_contradict(cur, b, c) is False

    def test_single_unresolved_identities_fall_back_to_pairwise(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Sarah Chen")

        assert cluster_names_contradict(cur, a, b) is True
