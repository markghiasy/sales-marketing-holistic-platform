"""Cross-cutting safety checks applied by every identity-resolution rule
(adapters/resolution/rules.py, linkedin_correlation.py) before an
automatic merge is allowed to actually apply — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
"Safety checks that apply across every identity rule".
"""

from __future__ import annotations

import re

_GENERIC_EMAIL_LOCAL_PARTS = {
    "support", "info", "admin", "sales", "team", "reception",
    "noreply", "contact", "hello", "office",
}

MAX_CLUSTER_SIZE = 8


def is_generic_role_email(email: str) -> bool:
    """True if the local part (before @) is a known generic/role address —
    several different humans legitimately sit behind support@, sales@,
    etc., so an exact match on one of these is never evidence of a
    single person."""
    local_part = email.split("@", 1)[0].lower()
    return local_part in _GENERIC_EMAIL_LOCAL_PARTS


def cluster_size_after_merge(cur, identity_a_id: str, identity_b_id: str) -> int:
    """How many distinct identities would end up sharing one person_id if
    identity_a_id and identity_b_id were merged. Counts each side's
    existing cluster (identities already resolved to that identity's
    person_id, or just the identity itself if unresolved), unions them,
    and returns the total distinct count — used to catch a shared
    identifier (e.g. an office switchboard number) bridging an
    implausible number of otherwise-unrelated people."""
    identity_ids: set[str] = set()
    for identity_id in (identity_a_id, identity_b_id):
        cur.execute("select person_id from identity where id = %s", (identity_id,))
        (person_id,) = cur.fetchone()
        if person_id is None:
            identity_ids.add(str(identity_id))
        else:
            cur.execute("select id from identity where person_id = %s", (person_id,))
            identity_ids.update(str(row[0]) for row in cur.fetchall())
    return len(identity_ids)


def has_existing_rejected_candidate(cur, identity_a_id: str, identity_b_id: str) -> bool:
    """True if a human has already rejected a link_candidate for this
    exact pair (in either order) — re-running the rules must not
    re-propose a pair a human already said no to."""
    cur.execute(
        """
        select 1 from link_candidate
        where status = 'rejected'
          and (
              (identity_a_id = %s and identity_b_id = %s)
              or (identity_a_id = %s and identity_b_id = %s)
          )
        limit 1
        """,
        (identity_a_id, identity_b_id, identity_b_id, identity_a_id),
    )
    return cur.fetchone() is not None


_NAME_TOKEN_RE = re.compile(r"[^\w]+")


def names_contradict(name_a: str | None, name_b: str | None) -> bool:
    """A cheap, explainable check for 'these are clearly different
    people' — not 'these are definitely the same person' (that's what
    the rest of the matching logic decides). Two names contradict if
    both are present, both are non-empty after normalising, and they
    share zero word tokens — a shared token (even just a first name)
    means this check stays silent and lets the rule's own match stand."""
    if not name_a or not name_b:
        return False
    tokens_a = {t for t in _NAME_TOKEN_RE.split(name_a.lower()) if t}
    tokens_b = {t for t in _NAME_TOKEN_RE.split(name_b.lower()) if t}
    if not tokens_a or not tokens_b:
        return False
    return tokens_a.isdisjoint(tokens_b)
