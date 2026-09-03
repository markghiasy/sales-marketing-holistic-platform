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
