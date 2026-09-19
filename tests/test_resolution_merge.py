# tests/test_resolution_merge.py
from __future__ import annotations

import uuid

import psycopg
import pytest

from adapters.resolution.merge import MergeConflictError, apply_merge, undo_merge


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

    def test_logs_a_merge_log_row_when_neither_identity_has_a_person(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")

        person_id = apply_merge(cur, a, b)

        cur.execute(
            """
            select identity_a_id, identity_b_id, survivor_person_id, absorbed_person_id,
                   moved_identity_ids, prev_primary_name, prev_preferred_name, reversed_at
            from merge_log
            where survivor_person_id = %s
            """,
            (person_id,),
        )
        row = cur.fetchone()
        assert row is not None
        (identity_a_id, identity_b_id, survivor_person_id, absorbed_person_id,
         moved_identity_ids, prev_primary_name, prev_preferred_name, reversed_at) = row
        assert str(identity_a_id) == a
        assert str(identity_b_id) == b
        assert str(survivor_person_id) == person_id
        assert absorbed_person_id is None
        assert sorted(moved_identity_ids) == sorted([a, b])
        assert prev_primary_name == ""
        assert prev_preferred_name is None
        assert reversed_at is None

    def test_logs_only_the_joining_identity_when_one_side_already_has_a_person(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        existing_person = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=existing_person)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")

        person_id = apply_merge(cur, a, b)

        cur.execute(
            "select absorbed_person_id, moved_identity_ids, prev_primary_name from merge_log where survivor_person_id = %s",
            (person_id,),
        )
        absorbed_person_id, moved_identity_ids, prev_primary_name = cur.fetchone()
        assert absorbed_person_id is None
        assert moved_identity_ids == [b]
        assert prev_primary_name == "Eric Tham"

    def test_logs_the_whole_absorbed_cluster_for_a_cluster_union_merge(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        person_a_id = str(cur.fetchone()[0])
        cur.execute("insert into person (primary_name) values ('E Tham') returning id")
        person_b_id = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=person_a_id)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric Tham", person_id=person_b_id)
        stranded = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", "Eric Tham", person_id=person_b_id)

        person_id = apply_merge(cur, a, b)

        cur.execute(
            "select absorbed_person_id, moved_identity_ids, prev_primary_name from merge_log where survivor_person_id = %s",
            (person_id,),
        )
        absorbed_person_id, moved_identity_ids, prev_primary_name = cur.fetchone()
        assert str(absorbed_person_id) == person_b_id
        assert sorted(moved_identity_ids) == sorted([b, stranded])
        assert prev_primary_name == "Eric Tham"

    def test_relocates_ai_brief_from_a_bare_identitys_own_pre_merge_key(self, db_conn: psycopg.Connection):
        # Real bug found 2026-09-19: merging two bare (unresolved)
        # identities each already had its own ai_brief row, keyed on its
        # own id (its pre-merge contact_key). Neither survived the merge
        # under the old code -- the contact showed "AI brief hasn't been
        # generated yet" despite two real ones existing in the table.
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")
        cur.execute(
            """
            insert into ai_brief (person_key, summary, context, topic, graph, urgency, model, prompt_version)
            values (%s, 'from a', '[]', 'General', '{}', 1, 'test', 'v1')
            """,
            (a,),
        )

        person_id = apply_merge(cur, a, b)

        cur.execute("select summary from ai_brief where person_key = %s", (person_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "from a"
        cur.execute("select count(*) from ai_brief where person_key = %s", (a,))
        assert cur.fetchone()[0] == 0  # the stale row is gone, not just uncounted

    def test_ai_brief_conflict_keeps_the_survivors_own_row(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")
        cur.execute(
            """
            insert into ai_brief (person_key, summary, context, topic, graph, urgency, model, prompt_version)
            values (%s, 'from a', '[]', 'General', '{}', 1, 'test', 'v1')
            """,
            (a,),
        )
        cur.execute(
            """
            insert into ai_brief (person_key, summary, context, topic, graph, urgency, model, prompt_version)
            values (%s, 'from b', '[]', 'General', '{}', 1, 'test', 'v1')
            """,
            (b,),
        )

        person_id = apply_merge(cur, a, b)  # must not raise a primary-key violation

        cur.execute("select count(*) from ai_brief where person_key = %s", (person_id,))
        assert cur.fetchone()[0] == 1
        cur.execute("select count(*) from ai_brief")
        assert cur.fetchone()[0] == 1  # both stale rows are gone, exactly one survives

    def test_relocates_contact_hidden_from_a_bare_identitys_own_pre_merge_key(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")
        cur.execute("insert into contact_hidden (contact_key) values (%s)", (a,))

        person_id = apply_merge(cur, a, b)

        cur.execute("select count(*) from contact_hidden where contact_key = %s", (person_id,))
        assert cur.fetchone()[0] == 1
        cur.execute("select count(*) from contact_hidden where contact_key = %s", (a,))
        assert cur.fetchone()[0] == 0


class TestUndoMerge:
    def test_undoing_a_cluster_union_merge_restores_both_clusters(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        person_a_id = str(cur.fetchone()[0])
        cur.execute("insert into person (primary_name) values ('E Tham') returning id")
        person_b_id = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=person_a_id)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric Tham", person_id=person_b_id)
        stranded = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", "Eric Tham", person_id=person_b_id)

        survivor_person_id = apply_merge(cur, a, b)
        cur.execute("select id from merge_log where survivor_person_id = %s", (survivor_person_id,))
        (merge_log_id,) = cur.fetchone()

        undo_merge(cur, str(merge_log_id))

        cur.execute("select person_id from identity where id = %s", (b,))
        assert str(cur.fetchone()[0]) == person_b_id
        cur.execute("select person_id from identity where id = %s", (stranded,))
        assert str(cur.fetchone()[0]) == person_b_id
        cur.execute("select person_id from identity where id = %s", (a,))
        assert str(cur.fetchone()[0]) == person_a_id  # untouched — never moved

        cur.execute("select merged_into from person where id = %s", (person_b_id,))
        assert cur.fetchone()[0] is None

        cur.execute("select primary_name from person where id = %s", (person_a_id,))
        assert cur.fetchone()[0] == "Eric Tham"  # restored prev_primary_name

        cur.execute("select reversed_at from merge_log where id = %s", (merge_log_id,))
        assert cur.fetchone()[0] is not None

    def test_undo_refuses_when_a_later_merge_touched_the_same_survivor(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        person_a_id = str(cur.fetchone()[0])
        cur.execute("insert into person (primary_name) values ('E Tham') returning id")
        person_b_id = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=person_a_id)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric Tham", person_id=person_b_id)

        survivor_person_id = apply_merge(cur, a, b)
        cur.execute("select id from merge_log where survivor_person_id = %s", (survivor_person_id,))
        (first_merge_log_id,) = cur.fetchone()

        # a second, later merge also lands on the same survivor person —
        # e.g. a third cluster gets folded in afterward
        c = _make_identity(cur, "linkedin", f"member-{uuid.uuid4().hex[:8]}", "Eric Tham")
        apply_merge(cur, a, c)

        with pytest.raises(MergeConflictError):
            undo_merge(cur, str(first_merge_log_id))

        # nothing changed — b is still on the survivor, not restored to person_b_id
        cur.execute("select person_id from identity where id = %s", (b,))
        assert str(cur.fetchone()[0]) == survivor_person_id
        cur.execute("select reversed_at from merge_log where id = %s", (first_merge_log_id,))
        assert cur.fetchone()[0] is None

    def test_undoing_a_first_time_merge_detaches_both_identities(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")

        person_id = apply_merge(cur, a, b)
        cur.execute("select id from merge_log where survivor_person_id = %s", (person_id,))
        (merge_log_id,) = cur.fetchone()

        undo_merge(cur, str(merge_log_id))

        cur.execute("select person_id from identity where id = %s", (a,))
        assert cur.fetchone()[0] is None
        cur.execute("select person_id from identity where id = %s", (b,))
        assert cur.fetchone()[0] is None
        # the now-empty person row is left in place, never deleted
        cur.execute("select id from person where id = %s", (person_id,))
        assert cur.fetchone() is not None

    def test_undoing_a_merge_resets_its_link_candidate_to_pending(self, db_conn: psycopg.Connection):
        # Found 2026-09-09: undo_merge reversed the identity/person state
        # but left the originating link_candidate stuck at 'confirmed',
        # so the review UI (which only lists status='pending' rows) never
        # surfaced the pair again for re-review even though the merge had
        # been undone.
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) "
            "values (%s, %s, 0.5, 'test', 'confirmed') returning id",
            (a, b),
        )
        (candidate_id,) = cur.fetchone()

        person_id = apply_merge(cur, a, b)
        cur.execute("select id from merge_log where survivor_person_id = %s", (person_id,))
        (merge_log_id,) = cur.fetchone()

        undo_merge(cur, str(merge_log_id))

        cur.execute("select status from link_candidate where id = %s", (candidate_id,))
        assert cur.fetchone()[0] == "pending"

    def test_undoing_a_join_merge_detaches_only_the_identity_that_joined(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Eric Tham') returning id")
        existing_person = str(cur.fetchone()[0])
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com", "Eric Tham", person_id=existing_person)
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net", "Eric")

        person_id = apply_merge(cur, a, b)
        cur.execute("select id from merge_log where survivor_person_id = %s", (person_id,))
        (merge_log_id,) = cur.fetchone()

        undo_merge(cur, str(merge_log_id))

        cur.execute("select person_id from identity where id = %s", (b,))
        assert cur.fetchone()[0] is None  # detached — this is the one that joined
        cur.execute("select person_id from identity where id = %s", (a,))
        assert str(cur.fetchone()[0]) == existing_person  # untouched — already belonged here
        cur.execute("select primary_name from person where id = %s", (existing_person,))
        assert cur.fetchone()[0] == "Eric Tham"  # restored (was already correct, but confirms no corruption)
