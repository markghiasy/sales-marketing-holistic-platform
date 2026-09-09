"""Applies a confirmed identity merge — the single place that creates
person rows and sets identity.person_id, used both by automatic rules
(adapters/resolution/rules.py) and the human-confirm route in
scripts/onboarding/app.py, so there's exactly one merge mechanism.

Every call writes a merge_log row before mutating anything, capturing
enough state to invert the merge — see
docs/superpowers/specs/2026-09-09-reversible-identity-merge-design.md.
"""

from __future__ import annotations

from .naming import select_names


class MergeConflictError(Exception):
    """Raised by undo_merge when a later merge already touched the same
    survivor person, so reversing this one could pull identities out from
    under a merge that was applied afterward."""


def apply_merge(cur, identity_a_id: str, identity_b_id: str) -> str:
    cur.execute("select person_id from identity where id = %s", (identity_a_id,))
    (person_a,) = cur.fetchone()
    cur.execute("select person_id from identity where id = %s", (identity_b_id,))
    (person_b,) = cur.fetchone()

    absorbed_person_id = None

    if person_a and person_b and person_a != person_b:
        # both identities already belong to different, already-merged
        # clusters (e.g. two separate link_candidate matches converge on
        # the same underlying person from different directions) — move
        # every identity in person_b's cluster over to person_a's,
        # rather than reassigning only identity_a_id/identity_b_id and
        # silently stranding the rest of person_b's cluster under a now-
        # orphaned, stale-named person row
        cur.execute("select id from identity where person_id = %s", (person_b,))
        moved_identity_ids = [str(row[0]) for row in cur.fetchall()]
        cur.execute("update identity set person_id = %s where person_id = %s", (person_a, person_b))
        # person.merged_into is exactly this schema's soft-merge pointer
        # (0001_init.sql: "reversible, never delete rows") — set it so
        # the losing person row still forwards to the survivor, rather
        # than leaving action/outreach rows (both FK to person) stranded
        # at a person with no identities and no way to follow the merge
        cur.execute("update person set merged_into = %s where id = %s", (person_a, person_b))
        person_id = person_a
        absorbed_person_id = person_b
    else:
        person_id = person_a or person_b
        if person_id is None:
            cur.execute("insert into person (primary_name) values ('') returning id")
            person_id = cur.fetchone()[0]
        # whichever of the two identities didn't already carry person_id
        # is the one actually moving — the other (if any) is already
        # exactly where it needs to be
        moved_identity_ids = [
            identity_id
            for identity_id, existing_person in ((identity_a_id, person_a), (identity_b_id, person_b))
            if existing_person != person_id
        ]

    cur.execute("select primary_name, preferred_name from person where id = %s", (person_id,))
    prev_primary_name, prev_preferred_name = cur.fetchone()

    cur.execute(
        """
        insert into merge_log
            (identity_a_id, identity_b_id, survivor_person_id, absorbed_person_id,
             moved_identity_ids, prev_primary_name, prev_preferred_name)
        values (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            identity_a_id,
            identity_b_id,
            person_id,
            absorbed_person_id,
            moved_identity_ids,
            prev_primary_name,
            prev_preferred_name,
        ),
    )

    cur.execute(
        "update identity set person_id = %s where id in (%s, %s)",
        (person_id, identity_a_id, identity_b_id),
    )

    # recompute naming over the WHOLE resulting cluster, not just the two
    # identities just merged — a later merge into an already-named person
    # must not regress primary_name to something worse just because this
    # call only saw two of the cluster's identities
    cur.execute("select display_name from identity where person_id = %s", (person_id,))
    display_names = [row[0] for row in cur.fetchall()]
    primary_name, preferred_name = select_names(display_names)

    cur.execute(
        "update person set primary_name = %s, preferred_name = %s where id = %s",
        (primary_name, preferred_name, person_id),
    )

    return str(person_id)


def undo_merge(cur, merge_log_id: str) -> None:
    cur.execute(
        """
        select absorbed_person_id, moved_identity_ids, prev_primary_name, prev_preferred_name,
               survivor_person_id, merged_at, identity_a_id, identity_b_id
        from merge_log
        where id = %s
        """,
        (merge_log_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no merge_log row with id {merge_log_id}")
    (absorbed_person_id, moved_identity_ids, prev_primary_name, prev_preferred_name,
     survivor_person_id, merged_at, identity_a_id, identity_b_id) = row

    # refuse if a later merge already built on the same survivor — it may
    # have absorbed more identities into this cluster, or relied on the
    # identities we're about to pull back out; the operator must undo that
    # later merge first
    cur.execute(
        "select id from merge_log where survivor_person_id = %s and merged_at > %s",
        (survivor_person_id, merged_at),
    )
    later = cur.fetchone()
    if later is not None:
        raise MergeConflictError(
            f"cannot undo merge {merge_log_id}: a later merge ({later[0]}) "
            f"already touched survivor person {survivor_person_id}"
        )

    if moved_identity_ids:
        cur.execute(
            "update identity set person_id = %s where id = any(%s::uuid[])",
            (absorbed_person_id, moved_identity_ids),
        )

    if absorbed_person_id is not None:
        cur.execute("update person set merged_into = null where id = %s", (absorbed_person_id,))

    cur.execute(
        "update person set primary_name = %s, preferred_name = %s where id = %s",
        (prev_primary_name, prev_preferred_name, survivor_person_id),
    )
    cur.execute("update merge_log set reversed_at = now() where id = %s", (merge_log_id,))

    # Put the originating link_candidate back to pending so the review UI
    # (which only lists status='pending' rows) surfaces it for re-review —
    # found 2026-09-09: undoing a merge with no link_candidate update left
    # it stuck 'confirmed' with no way to see or re-decide it from the
    # dashboard, even though the underlying merge had been reversed.
    # identity_a_id/identity_b_id are recorded in the same order apply_merge
    # (and its only caller, the confirm route) was called with, so an exact
    # match is safe here — no need to check both orderings.
    cur.execute(
        """
        update link_candidate set status = 'pending'
        where identity_a_id = %s and identity_b_id = %s and status = 'confirmed'
        """,
        (identity_a_id, identity_b_id),
    )
