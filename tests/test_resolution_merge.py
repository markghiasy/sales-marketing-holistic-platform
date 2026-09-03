# tests/test_resolution_merge.py
from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.merge import apply_merge


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


class TestApplyMerge:
    def test_creates_a_new_person_when_neither_identity_has_one(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")

        person_id = apply_merge(cur, a, b)

        cur.execute("select person_id from identity where id = %s", (a,))
        assert str(cur.fetchone()[0]) == person_id
        cur.execute("select person_id from identity where id = %s", (b,))
        assert str(cur.fetchone()[0]) == person_id

        cur.execute("select primary_name, preferred_name from person where id = %s", (person_id,))
        primary, preferred = cur.fetchone()
        assert primary == "Eric Tham"
        assert preferred == "Eric"

    def test_reuses_an_existing_person_id_from_one_side(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        existing_person = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=existing_person)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")

        person_id = apply_merge(cur, a, b)

        assert person_id == existing_person
        cur.execute("select person_id from identity where id = %s", (b,))
        assert str(cur.fetchone()[0]) == existing_person

    def test_renaming_considers_the_whole_resulting_cluster_not_just_the_pair(self, db_conn: psycopg.Connection):
        # a person already has one identity ("Eric Tham"); merging in a
        # second, unrelated-looking short name ("E.T.") should still keep
        # "Eric Tham" as primary_name, not get confused by only looking at
        # the two identities in *this* merge call
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        existing_person = str(cur.fetchone()[0])
        _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=existing_person)
        a = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric Tham", person_id=existing_person)
        b = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", "E T")

        person_id = apply_merge(cur, a, b)

        cur.execute("select primary_name from person where id = %s", (person_id,))
        assert cur.fetchone()[0] == "Eric Tham"

    def test_merging_two_already_linked_clusters_unifies_them(self, db_conn: psycopg.Connection):
        # a and b each already belong to a DIFFERENT existing person —
        # this happens when two separate link_candidate matches converge
        # on the same underlying real person from different directions.
        # Merging a and b must fold the whole of person_b's cluster into
        # person_a's, not just move a and b themselves and strand
        # person_b's other identity under a now-orphaned person row.
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        person_a_id = str(cur.fetchone()[0])
        cur.execute("insert into person (primary_name) values ('E Tham') returning id")
        person_b_id = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=person_a_id)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric Tham", person_id=person_b_id)
        stranded = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", "Eric Tham", person_id=person_b_id)

        person_id = apply_merge(cur, a, b)

        # the identity that was never passed to apply_merge, but shared
        # person_b's cluster, must have followed the merge
        cur.execute("select person_id from identity where id = %s", (stranded,))
        assert str(cur.fetchone()[0]) == person_id

    def test_folding_sets_merged_into_on_the_losing_person(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        person_a_id = str(cur.fetchone()[0])
        cur.execute("insert into person (primary_name) values ('E Tham') returning id")
        person_b_id = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=person_a_id)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric Tham", person_id=person_b_id)

        apply_merge(cur, a, b)

        cur.execute("select merged_into from person where id = %s", (person_b_id,))
        assert str(cur.fetchone()[0]) == person_a_id
