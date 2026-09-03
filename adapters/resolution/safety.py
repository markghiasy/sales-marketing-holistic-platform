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


def has_existing_candidate(cur, identity_a_id: str, identity_b_id: str) -> bool:
    """True if ANY link_candidate row already exists for this pair (in
    either order), regardless of status — makes re-running the rules
    idempotent: a rule must not re-propose (and the automatic rules must
    not re-apply) a pair that a previous run already decided, confirmed,
    or already queued for review. Supersedes the narrower
    "rejected-only" check this function used to be — a pending or
    confirmed candidate from a prior run needs exactly the same
    protection, or every rerun duplicates the review queue forever."""
    cur.execute(
        """
        select 1 from link_candidate
        where (identity_a_id = %s and identity_b_id = %s)
           or (identity_a_id = %s and identity_b_id = %s)
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


def _cluster_display_names(cur, identity_id: str) -> list[str | None]:
    """Every display_name already in identity_id's cluster — the whole
    person's worth of identities if it's already resolved, or just
    itself if not."""
    cur.execute("select person_id from identity where id = %s", (identity_id,))
    (person_id,) = cur.fetchone()
    if person_id is None:
        cur.execute("select display_name from identity where id = %s", (identity_id,))
        return [cur.fetchone()[0]]
    cur.execute("select display_name from identity where person_id = %s", (person_id,))
    return [row[0] for row in cur.fetchall()]


def cluster_names_contradict(cur, identity_a_id: str, identity_b_id: str) -> bool:
    """Like names_contradict, but checks every display_name already in
    EITHER identity's existing cluster against every display_name in the
    other's — not just the two identities named in this call. Without
    this, a transitive merge (A-B already merged because B has no name
    to contradict with, then B-C proposed) never catches a contradiction
    between A and C, since C is only ever compared against B directly.
    See docs/superpowers/plans/2026-09-03-identity-resolution-phase1.md,
    Fix 12.3."""
    names_a = _cluster_display_names(cur, identity_a_id)
    names_b = _cluster_display_names(cur, identity_b_id)
    return any(names_contradict(na, nb) for na in names_a for nb in names_b)
