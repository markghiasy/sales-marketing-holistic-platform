"""Applies a confirmed identity merge — the single place that creates
person rows and sets identity.person_id, used both by automatic rules
(adapters/resolution/rules.py) and the human-confirm route in
scripts/onboarding/app.py, so there's exactly one merge mechanism.
"""

from __future__ import annotations

from .naming import select_names


def apply_merge(cur, identity_a_id: str, identity_b_id: str) -> str:
    cur.execute("select person_id from identity where id = %s", (identity_a_id,))
    (person_a,) = cur.fetchone()
    cur.execute("select person_id from identity where id = %s", (identity_b_id,))
    (person_b,) = cur.fetchone()

    if person_a and person_b and person_a != person_b:
        # both identities already belong to different, already-merged
        # clusters (e.g. two separate link_candidate matches converge on
        # the same underlying person from different directions) — move
        # every identity in person_b's cluster over to person_a's,
        # rather than reassigning only identity_a_id/identity_b_id and
        # silently stranding the rest of person_b's cluster under a now-
        # orphaned, stale-named person row
        cur.execute("update identity set person_id = %s where person_id = %s", (person_a, person_b))
        # person.merged_into is exactly this schema's soft-merge pointer
        # (0001_init.sql: "reversible, never delete rows") — set it so
        # the losing person row still forwards to the survivor, rather
        # than leaving action/outreach rows (both FK to person) stranded
        # at a person with no identities and no way to follow the merge
        cur.execute("update person set merged_into = %s where id = %s", (person_a, person_b))
        person_id = person_a
    else:
        person_id = person_a or person_b
        if person_id is None:
            cur.execute("insert into person (primary_name) values ('') returning id")
            person_id = cur.fetchone()[0]

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
