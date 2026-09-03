# Identity Resolution Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build §8's identity-resolution ladder (Rules 1-6) plus Phase 1's structured-source knowledge-graph facts, with a human review queue in the existing ops dashboard, all without any model API call.

**Architecture:** A new `adapters/resolution/` package reads from tables already populated by Block A's adapters (`identity`, `graph_contact`, `linkedin_connection`, `message`) and writes `link_candidate`/`fact`/`person`/`organization` rows. Automatic rules (1-3) write an already-`confirmed` `link_candidate` row (subject to safety checks) rather than writing `identity.person_id` directly, so every merge — automatic or not — is auditable. Rules 4-5 always write `pending` rows for human review via new `/resolution` routes on the existing Flask ops dashboard.

**Tech Stack:** Python, psycopg (raw SQL, matching `adapters/store_writer.py`'s existing style), pytest against the real local Postgres via the existing `db_conn` fixture, Flask (existing `scripts/onboarding/app.py`).

## Global Constraints

- Precision over recall, from §8 verbatim: "optimise for precision, accept low recall early." No rule may auto-merge two identities without going through the safety checks below first.
- Every rule, automatic or not, must produce an auditable `link_candidate` row — no rule writes `identity.person_id` directly without one.
- No Splink, no Neo4j, no separate evidence-graph system — decided in the design doc, not open for reconsideration in this plan.
- No `organization` fuzzy-variant matching (e.g. "Commonwealth Bank" vs "CBA") — exact-normalised-name dedup only (lowercase, trimmed, common suffix stripped: "inc", "inc.", "ltd", "ltd.", "llc", "co", "co.", "corp", "corp.").
- WhatsApp `identity.handle` is the raw JID (`<digits>@s.whatsapp.net` for a person, `<digits>@g.us` for a group) — **not** E.164, no leading `+`. Every rule comparing a WhatsApp handle to `graph_contact.phones[]` must extract the digit portion before `@` first, and must skip `@g.us` handles entirely (a group chat is not a person).
- `graph_contact.phones[]` is digits-only (no `+`, no separators) — this repo's existing normalisation, from `adapters/outlook/contacts_sync.py`'s `_normalise_phone`. Reuse it; do not reimplement.
- This account's `graph_contact` table is currently empty (real, verified — not a bug) — Rules 2 and 3 will find zero matches when run for real today. Tests must still cover them with fixture data; do not skip testing a rule because production data is currently sparse.
- Every SQL statement follows this repo's existing style: raw SQL via `psycopg`, `%s` placeholders, `on conflict ... do nothing`/`do update` for idempotency where relevant — matching `adapters/store_writer.py`.

---

### Task 1: Migration — schema for fact, organization, and two new columns

**Files:**
- Create: `db/migrations/0005_identity_resolution.sql`

**Interfaces:**
- Produces: tables `fact`, `organization`; columns `person.preferred_name`, `link_candidate.reason` — every later task depends on this migration having run.

- [ ] **Step 1: Write the migration**

```sql
-- db/migrations/0005_identity_resolution.sql
-- Identity resolution (§8) + Phase 1 knowledge-graph facts (§10 upgrade).
-- See docs/superpowers/specs/2026-09-03-identity-resolution-design.md.

alter table person add column preferred_name text;
alter table link_candidate add column reason text;

create table organization (
    id            uuid primary key default gen_random_uuid(),
    canonical_name text not null unique  -- normalised: lowercase, trimmed,
                                          -- common suffix stripped
);

create table fact (
    id                 uuid primary key default gen_random_uuid(),
    subject_identity_id uuid not null references identity(id),
    fact_type          text not null,                       -- closed vocabulary,
                                                              -- see adapters/resolution/facts.py
    object_text        text,                                -- fallback for values with
                                                              -- no canonical entity yet
    object_identity_id uuid references identity(id),         -- set when the object is
                                                              -- also an identity
    object_org_id      uuid references organization(id),     -- set when the object is
                                                              -- an organisation
    confidence         real not null,
    source             text not null,                        -- e.g. 'linkedin_connection'
    source_message_id  uuid references message(id),           -- null for structured-source facts
    status             text not null default 'pending',       -- 'pending' | 'confirmed' | 'rejected'
    reason             text,
    model              text,                                  -- null until Phase 2
    prompt_version     text,                                  -- null until Phase 2
    extracted_at       timestamptz not null default now(),
    reviewed_at        timestamptz
);

create index on fact (subject_identity_id);
create index on fact (status);
create index on link_candidate (status);
```

- [ ] **Step 2: Apply it locally and verify**

Run: `docker compose up -d` (if not already running), then:
```bash
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms < db/migrations/0005_identity_resolution.sql
```
Expected: no errors. Then verify:
```bash
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms -c "\d fact" -c "\d organization" -c "\d person" -c "\d link_candidate"
```
Expected: `fact` and `organization` tables listed with the columns above; `person` shows `preferred_name`; `link_candidate` shows `reason`.

- [ ] **Step 3: Commit**

```bash
git add db/migrations/0005_identity_resolution.sql
git commit -m "Add identity-resolution schema: fact, organization, person.preferred_name, link_candidate.reason"
```

---

### Task 2: Safety checks (`adapters/resolution/safety.py`)

**Files:**
- Create: `adapters/resolution/__init__.py` (empty)
- Create: `adapters/resolution/safety.py`
- Test: `tests/test_resolution_safety.py`

**Interfaces:**
- Consumes: `psycopg.Cursor` (real, via the existing `db_conn` fixture in tests).
- Produces (used by Task 5's rules and Task 9's `merge.py`):
  - `is_generic_role_email(email: str) -> bool`
  - `cluster_size_after_merge(cur, identity_a_id: str, identity_b_id: str) -> int`
  - `has_existing_rejected_candidate(cur, identity_a_id: str, identity_b_id: str) -> bool`
  - `names_contradict(name_a: str | None, name_b: str | None) -> bool`
  - `MAX_CLUSTER_SIZE: int` (module constant, value `8`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolution_safety.py
from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.safety import (
    MAX_CLUSTER_SIZE,
    cluster_size_after_merge,
    has_existing_rejected_candidate,
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


class TestHasExistingRejectedCandidate:
    def test_no_rejected_candidate_returns_false(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        a = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex}@example.com")
        b = _make_identity(cur, "whatsapp", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net")

        assert has_existing_rejected_candidate(cur, a, b) is False

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

        assert has_existing_rejected_candidate(cur, a, b) is True
        assert has_existing_rejected_candidate(cur, b, a) is True  # order-independent

    def test_pending_candidate_does_not_count_as_rejected(self, db_conn: psycopg.Connection):
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

        assert has_existing_rejected_candidate(cur, a, b) is False


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_safety.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/__init__.py
```

```python
# adapters/resolution/safety.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_safety.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/ tests/test_resolution_safety.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/__init__.py adapters/resolution/safety.py tests/test_resolution_safety.py
git commit -m "Add identity-resolution safety checks (generic identifiers, cluster size, rejection durability, name contradiction)"
```

---

### Task 3: Person naming (`adapters/resolution/naming.py`)

**Files:**
- Create: `adapters/resolution/naming.py`
- Test: `tests/test_resolution_naming.py`

**Interfaces:**
- Produces (used by Task 8's `merge.py`): `select_names(display_names: list[str | None]) -> tuple[str, str | None]` — returns `(primary_name, preferred_name)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolution_naming.py
from __future__ import annotations

from adapters.resolution.naming import select_names


def test_picks_longest_name_like_candidate_as_primary():
    primary, preferred = select_names(["Eric Tham", "Eric"])
    assert primary == "Eric Tham"
    assert preferred == "Eric"


def test_no_preferred_name_when_only_one_candidate():
    primary, preferred = select_names(["Eric Tham"])
    assert primary == "Eric Tham"
    assert preferred is None


def test_no_preferred_name_when_all_candidates_identical():
    primary, preferred = select_names(["Eric Tham", "Eric Tham"])
    assert primary == "Eric Tham"
    assert preferred is None


def test_filters_out_handle_like_candidates():
    # a single lowercase word with no space looks like a username, not a
    # real name, and should be excluded from consideration entirely
    primary, preferred = select_names(["Eric Tham", "eric_t99"])
    assert primary == "Eric Tham"
    assert preferred is None


def test_falls_back_to_first_candidate_when_nothing_looks_name_like():
    primary, preferred = select_names(["eric_t99", "12345"])
    assert primary == "eric_t99"
    assert preferred is None


def test_ignores_none_and_empty_candidates():
    primary, preferred = select_names(["Eric Tham", None, "", "Eric"])
    assert primary == "Eric Tham"
    assert preferred == "Eric"


def test_empty_input_raises():
    import pytest
    with pytest.raises(ValueError):
        select_names([])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_naming.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution.naming'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/naming.py
"""Chooses person.primary_name / preferred_name from the display names of
every identity being merged into one person — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
"Naming a merged person". Best-effort, not a guarantee.
"""

from __future__ import annotations

import re

_NAME_LIKE_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]*(\s+[A-Za-z][A-Za-z'\-]*)*$")


def _looks_name_like(candidate: str) -> bool:
    """One or more alphabetic tokens separated by spaces (allowing
    apostrophes/hyphens within a token, e.g. "O'Brien") — a single word
    like "Eric" passes (it's a plausible short/preferred name), but
    anything with digits or underscores, like a username, doesn't."""
    return bool(_NAME_LIKE_RE.match(candidate.strip()))


def select_names(display_names: list[str | None]) -> tuple[str, str | None]:
    """Returns (primary_name, preferred_name). display_names is every
    identity's display_name in the resulting merged cluster, in no
    particular order. Raises ValueError if given no candidates at all
    (a merge always involves at least one real identity)."""
    candidates = [d.strip() for d in display_names if d and d.strip()]
    if not candidates:
        raise ValueError("select_names requires at least one non-empty candidate")

    name_like = [c for c in candidates if _looks_name_like(c)]

    if not name_like:
        return candidates[0], None

    name_like_sorted = sorted(set(name_like), key=len, reverse=True)
    primary = name_like_sorted[0]
    shorter_distinct = [c for c in name_like_sorted[1:] if c != primary]
    preferred = shorter_distinct[0] if shorter_distinct else None
    return primary, preferred
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_naming.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/naming.py tests/test_resolution_naming.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/naming.py tests/test_resolution_naming.py
git commit -m "Add person primary_name/preferred_name selection"
```

---

### Task 4: Organizations (`adapters/resolution/organizations.py`)

**Files:**
- Create: `adapters/resolution/organizations.py`
- Test: `tests/test_resolution_organizations.py`

**Interfaces:**
- Produces (used by Task 7's structured facts): `get_or_create_organization(cur, raw_name: str) -> str` — returns `organization.id`. `normalise_org_name(raw_name: str) -> str` (exposed for tests and for Task 7's fact-lookup path).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolution_organizations.py
from __future__ import annotations

import psycopg

from adapters.resolution.organizations import get_or_create_organization, normalise_org_name


class TestNormaliseOrgName:
    def test_lowercases_and_trims(self):
        assert normalise_org_name("  Acme  ") == "acme"

    def test_strips_common_suffixes(self):
        assert normalise_org_name("Acme Inc") == "acme"
        assert normalise_org_name("Acme Inc.") == "acme"
        assert normalise_org_name("Acme Ltd") == "acme"
        assert normalise_org_name("Acme Corp") == "acme"

    def test_does_not_merge_genuine_variants(self):
        # this is the point of NOT doing fuzzy matching — these stay
        # different normalised strings on purpose
        assert normalise_org_name("Commonwealth Bank") != normalise_org_name("CBA")


class TestGetOrCreateOrganization:
    def test_creates_a_new_organization(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        org_id = get_or_create_organization(cur, "Acme Inc")

        cur.execute("select canonical_name from organization where id = %s", (org_id,))
        assert cur.fetchone()[0] == "acme"

    def test_reuses_existing_organization_for_a_suffix_variant(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        id1 = get_or_create_organization(cur, "Acme Inc")
        id2 = get_or_create_organization(cur, "Acme")

        assert id1 == id2

    def test_keeps_genuine_variants_as_separate_rows(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        id1 = get_or_create_organization(cur, "Commonwealth Bank")
        id2 = get_or_create_organization(cur, "CBA")

        assert id1 != id2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_organizations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution.organizations'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/organizations.py
"""Canonical organisation dedup for knowledge-graph facts — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
"Canonical organisations, not free text". Exact-normalised-name dedup
only; deliberately no fuzzy variant matching (that's the kind of guess
that creates false merges, just for companies instead of people).
"""

from __future__ import annotations

import re

_SUFFIX_RE = re.compile(
    r"\s+(inc|inc\.|ltd|ltd\.|llc|co|co\.|corp|corp\.)$", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"\s+")


def normalise_org_name(raw_name: str) -> str:
    name = raw_name.strip()
    name = _SUFFIX_RE.sub("", name)
    name = _WHITESPACE_RE.sub(" ", name).strip()
    return name.lower()


def get_or_create_organization(cur, raw_name: str) -> str:
    canonical = normalise_org_name(raw_name)
    cur.execute(
        """
        insert into organization (canonical_name)
        values (%s)
        on conflict (canonical_name) do update set canonical_name = excluded.canonical_name
        returning id
        """,
        (canonical,),
    )
    return str(cur.fetchone()[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_organizations.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/organizations.py tests/test_resolution_organizations.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/organizations.py tests/test_resolution_organizations.py
git commit -m "Add canonical organization dedup for knowledge-graph facts"
```

---

### Task 5: Merge application (`adapters/resolution/merge.py`)

**Files:**
- Create: `adapters/resolution/merge.py`
- Test: `tests/test_resolution_merge.py`

**Interfaces:**
- Consumes: `adapters.resolution.naming.select_names`.
- Produces (used by Task 6's rules and Task 10's review-queue routes): `apply_merge(cur, identity_a_id: str, identity_b_id: str) -> str` — creates/reuses a `person` row, sets `identity.person_id` on both sides, recomputes `primary_name`/`preferred_name` over the *whole* resulting cluster (not just the two identities just merged), returns the resulting `person.id`. If `identity_a_id` and `identity_b_id` already belong to two different, already-merged clusters (e.g. two separate `link_candidate` matches converge on the same real person from different directions), the whole of the second cluster is folded into the first — this is the single merge mechanism, so it must never silently strand part of a cluster.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution.merge'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/merge.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_merge.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/merge.py tests/test_resolution_merge.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/merge.py tests/test_resolution_merge.py
git commit -m "Add identity merge application, shared by automatic rules and the review queue"
```

---

### Task 6: Rules 1 & 3 (exact email, contact bridge) — `adapters/resolution/rules.py`

**Decision (2026-09-03, confirmed with Eva):** §8's Rule 2 ("exact phone
match") is folded into Rule 3 (the contact bridge) rather than
implemented separately. Reasoning: a bare phone-only match with no
corroborating email is weaker evidence than the other automatic rules,
and has no second identity to merge into on its own — `graph_contact`
isn't itself an identity. Rule 3 already requires a contact record with
*both* an email (→ Outlook identity) and a phone (→ WhatsApp identity)
before proposing a merge, which is exactly the corroborated case Rule 2
was reaching for. No `rule_exact_phone_match` function exists in this
plan; `rule_contact_bridge` is the only phone-matching rule.

**Files:**
- Create: `adapters/resolution/rules.py`
- Test: `tests/test_resolution_rules.py`

**Interfaces:**
- Consumes: `adapters.resolution.safety` (all four functions + `MAX_CLUSTER_SIZE`), `adapters.resolution.merge.apply_merge`.
- Produces (used by Task 9's `run.py`): `rule_exact_email_match(cur) -> int`, `rule_contact_bridge(cur) -> int` — each returns the count of candidates it wrote (auto-confirmed or queued).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution.rules'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/rules.py
"""Rules 1 & 3 of §8's identity-resolution ladder — exact email match
and the contact bridge. §8's Rule 2 (exact phone match) is folded into
Rule 3 here rather than implemented separately: a phone-only match with
no corroborating email has no second identity to merge into on its own
(graph_contact isn't itself an identity), and is weaker evidence than
the other automatic rules anyway — decided with Eva 2026-09-03, see
Task 6's header note. Both rules here are "automatic": they write an
already-confirmed link_candidate row (not a bare identity.person_id
write — see the design doc's "Evidence provenance" section for why),
subject to the safety checks in safety.py. See
docs/superpowers/specs/2026-09-03-identity-resolution-design.md.
"""

from __future__ import annotations

from .merge import apply_merge
from .safety import (
    MAX_CLUSTER_SIZE,
    cluster_size_after_merge,
    has_existing_rejected_candidate,
    is_generic_role_email,
    names_contradict,
)


def _whatsapp_phone_digits(handle: str) -> str | None:
    """Extracts the digit portion of a WhatsApp identity.handle (a raw
    JID like '15806709090@s.whatsapp.net'), or None for a group chat
    ('...@g.us') or anything not shaped like a person's number."""
    if handle.endswith("@g.us"):
        return None
    if "@" not in handle:
        return None
    digits = handle.split("@", 1)[0]
    return digits if digits.isdigit() else None


def _propose_and_maybe_confirm(
    cur, identity_a_id: str, identity_b_id: str, method: str, reason: str, blocked_reason: str | None
) -> bool:
    """Writes one link_candidate row for the pair. If blocked_reason is
    given, or a safety check fails, status is 'pending' and no merge is
    applied. Otherwise status is 'confirmed' and the merge is applied
    immediately. Returns True if a row was written (it always is, unless
    a rejected candidate for this pair already exists, in which case
    nothing is written and this returns False)."""
    if has_existing_rejected_candidate(cur, identity_a_id, identity_b_id):
        return False

    full_reason = reason
    status = "confirmed"

    if blocked_reason:
        status = "pending"
        full_reason = f"{reason} — {blocked_reason}"
    elif names_contradict(*_display_names(cur, identity_a_id, identity_b_id)):
        status = "pending"
        full_reason = f"{reason} — contradicting display names, needs review"
    elif cluster_size_after_merge(cur, identity_a_id, identity_b_id) > MAX_CLUSTER_SIZE:
        status = "pending"
        full_reason = f"{reason} — merge would create an implausibly large cluster, needs review"

    cur.execute(
        """
        insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason)
        values (%s, %s, 1.0, %s, %s, %s)
        """,
        (identity_a_id, identity_b_id, method, status, full_reason),
    )

    if status == "confirmed":
        apply_merge(cur, identity_a_id, identity_b_id)

    return True


def _display_names(cur, identity_a_id: str, identity_b_id: str) -> tuple[str | None, str | None]:
    cur.execute("select display_name from identity where id = %s", (identity_a_id,))
    name_a = cur.fetchone()[0]
    cur.execute("select display_name from identity where id = %s", (identity_b_id,))
    name_b = cur.fetchone()[0]
    return name_a, name_b


def rule_exact_email_match(cur) -> int:
    cur.execute(
        """
        select i.id, i.handle, lc.id, lc.email, lc.first_name, lc.last_name
        from identity i
        join linkedin_connection lc on lower(lc.email) = i.handle
        where i.channel = 'outlook' and lc.email is not null and lc.email != ''
        """
    )
    rows = cur.fetchall()
    count = 0
    for outlook_identity_id, email, connection_id, _, first_name, last_name in rows:
        # display_name must come from the LinkedIn connection's name here —
        # without it, the newly-created linkedin identity always has a NULL
        # display_name, which silently disables the names_contradict safety
        # check below for every Rule 1 match (found while hand-tracing this
        # rule against its own test before dispatch — a real defect, not
        # just a test gap)
        linkedin_display_name = f"{first_name or ''} {last_name or ''}".strip() or None
        cur.execute(
            "insert into identity (channel, handle, display_name) values ('linkedin', %s, %s) on conflict (channel, handle) do nothing",
            (connection_id, linkedin_display_name),
        )
        cur.execute(
            "select id from identity where channel = 'linkedin' and handle = %s", (connection_id,)
        )
        linkedin_identity_id = str(cur.fetchone()[0])

        blocked_reason = (
            f"generic role address {email} — not merged automatically"
            if is_generic_role_email(email)
            else None
        )
        reason = f"exact email match on {email}"
        if _propose_and_maybe_confirm(
            cur, str(outlook_identity_id), linkedin_identity_id, "exact_email", reason, blocked_reason
        ):
            count += 1
    return count


def rule_contact_bridge(cur) -> int:
    cur.execute("select id, emails, phones, display_name from graph_contact")
    contacts = cur.fetchall()
    count = 0
    for _contact_id, emails, phones, contact_display_name in contacts:
        if not emails or not phones:
            continue
        outlook_identity_id = None
        for email in emails:
            cur.execute(
                "select id from identity where channel = 'outlook' and handle = %s", (email.lower(),)
            )
            row = cur.fetchone()
            if row:
                outlook_identity_id = str(row[0])
                break
        if outlook_identity_id is None:
            continue

        whatsapp_identity_id = None
        cur.execute("select id, handle from identity where channel = 'whatsapp'")
        for wa_id, handle in cur.fetchall():
            digits = _whatsapp_phone_digits(handle)
            if digits and digits in phones:
                whatsapp_identity_id = str(wa_id)
                break
        if whatsapp_identity_id is None:
            continue

        reason = f"contact record {contact_display_name or '(no name)'} links this email and phone"
        if _propose_and_maybe_confirm(
            cur, outlook_identity_id, whatsapp_identity_id, "contact_bridge", reason, None
        ):
            count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_rules.py -v`
Expected: PASS (all tests in the file: Rule 1's 4 tests, Rule 3's 4 tests)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/rules.py tests/test_resolution_rules.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/rules.py tests/test_resolution_rules.py
git commit -m "Add Rules 1 & 3: exact email match, contact bridge (Rule 2 folded into Rule 3)"
```

---

### Task 7: Rule 4 — signature phone scan

**Files:**
- Modify: `adapters/resolution/rules.py`
- Test: `tests/test_resolution_rules.py` (extend)

**Interfaces:**
- Consumes: `adapters.outlook.contacts_sync._normalise_phone`, same `_whatsapp_phone_digits` helper from Task 6.
- Produces (used by Task 9's `run.py`): `rule_signature_phone(cur) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_resolution_rules.py
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
        wa_id = _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Eric Tham")
        thread = _make_thread(cur)
        body = f"Thanks,\nEric Tham\nMobile: {digits}"
        _make_message(cur, thread, outlook_id, body, direction="outbound")

        count = rule_signature_phone(cur)

        assert count == 1
        cur.execute(
            "select status, score, method from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )
        status, score, method = cur.fetchone()
        assert status == "pending"
        assert score == 0.8
        assert method == "email_signature_phone"

    def test_inbound_messages_are_not_scanned(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Someone Else")
        thread = _make_thread(cur)
        _make_message(cur, thread, outlook_id, f"call me on {digits}", direction="inbound")

        count = rule_signature_phone(cur)

        assert count == 0

    def test_number_outside_the_last_few_lines_is_not_matched(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        digits = "1580" + str(uuid.uuid4().int)[:6]  # digits only — .hex contains a-f letters
        _make_identity(cur, "whatsapp", f"{digits}@s.whatsapp.net", "Someone Else")
        thread = _make_thread(cur)
        padding = "\n".join(f"line {n}" for n in range(20))
        body = f"By the way my number is {digits}\n{padding}\nThanks,\nEric"
        _make_message(cur, thread, outlook_id, body, direction="outbound")

        count = rule_signature_phone(cur)

        assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_rules.py::TestRuleSignaturePhone -v`
Expected: FAIL with `ImportError: cannot import name 'rule_signature_phone'`

- [ ] **Step 3: Write the implementation**

First, add two new imports to the existing top-of-file import block in
`adapters/resolution/rules.py` (do not append them at the bottom with the
rest of this step's code — Python imports belong at the top of the file,
and `ruff` will flag `E402` otherwise). The file currently starts:

```python
from __future__ import annotations

from .merge import apply_merge
from .safety import (
    ...
)
```

Change it to:

```python
from __future__ import annotations

import re

from adapters.outlook.contacts_sync import _normalise_phone

from .merge import apply_merge
from .safety import (
    ...
)
```

(`re` and `_normalise_phone` are new; the `from .merge import` and
`from .safety import (...)` lines are unchanged — leave them exactly as
Task 6 wrote them.)

Then append the following to the end of `adapters/resolution/rules.py`:

```python
_SIGNATURE_LINES = 6  # how many trailing lines of body_text count as
                       # "the signature block" for phone scanning
_PHONE_CANDIDATE_RE = re.compile(r"[\d][\d\s().-]{6,}\d")


def _extract_signature_phone_digits(body_text: str) -> list[str]:
    lines = [line for line in body_text.strip().splitlines() if line.strip()]
    signature_region = "\n".join(lines[-_SIGNATURE_LINES:])
    candidates = []
    for match in _PHONE_CANDIDATE_RE.finditer(signature_region):
        digits = _normalise_phone(match.group())
        if len(digits) >= 7:  # shorter than this isn't a plausible phone number
            candidates.append(digits)
    return candidates


def rule_signature_phone(cur) -> int:
    cur.execute(
        """
        select id, from_identity_id, body_text
        from message
        where channel = 'outlook' and direction = 'outbound'
        """
    )
    messages = cur.fetchall()
    count = 0
    for message_id, from_identity_id, body_text in messages:
        if from_identity_id is None or not body_text:
            continue
        for digits in _extract_signature_phone_digits(body_text):
            cur.execute("select id, handle from identity where channel = 'whatsapp'")
            for wa_id, handle in cur.fetchall():
                wa_digits = _whatsapp_phone_digits(handle)
                if wa_digits == digits:
                    if has_existing_rejected_candidate(cur, str(from_identity_id), str(wa_id)):
                        continue
                    reason = f"phone {digits} found in signature of message {message_id}, matches WhatsApp handle {wa_digits}"
                    cur.execute(
                        """
                        insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason)
                        values (%s, %s, 0.8, 'email_signature_phone', 'pending', %s)
                        """,
                        (str(from_identity_id), str(wa_id), reason),
                    )
                    count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_rules.py -v`
Expected: PASS (all tests in the file, including Rule 1/3's tests from Task 6)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/rules.py tests/test_resolution_rules.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/rules.py tests/test_resolution_rules.py
git commit -m "Add Rule 4: phone number in an email signature, queued for review"
```

---

### Task 8: Rule 5 — LinkedIn name + organisation correlation

**Files:**
- Create: `adapters/resolution/linkedin_correlation.py`
- Test: `tests/test_resolution_linkedin_correlation.py`

**Interfaces:**
- Consumes: `adapters.resolution.safety.has_existing_rejected_candidate`.
- Produces (used by Task 9's `run.py`): `rule_linkedin_correlation(cur) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolution_linkedin_correlation.py
from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.linkedin_correlation import rule_linkedin_correlation


def _make_identity(cur, channel: str, handle: str, display_name: str | None = None) -> str:
    cur.execute(
        "insert into identity (channel, handle, display_name) values (%s, %s, %s) returning id",
        (channel, handle, display_name),
    )
    return str(cur.fetchone()[0])


def _make_linkedin_connection(cur, first_name: str, last_name: str, company: str | None = None) -> str:
    conn_id = f"https://linkedin.com/in/{uuid.uuid4().hex[:10]}"
    cur.execute(
        "insert into linkedin_connection (id, first_name, last_name, company) values (%s, %s, %s, %s)",
        (conn_id, first_name, last_name, company),
    )
    return conn_id


class TestRuleLinkedinCorrelation:
    def test_exact_name_match_queues_a_candidate_never_confirmed(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")

        count = rule_linkedin_correlation(cur)

        assert count == 1
        cur.execute(
            "select status, method, score from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )
        status, method, score = cur.fetchone()
        assert status == "pending"
        assert method == "linkedin_name_company"
        cur.execute("select person_id from identity where id = %s", (outlook_id,))
        assert cur.fetchone()[0] is None

    def test_no_match_for_unrelated_names(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_identity(cur, "outlook", f"sarah-{uuid.uuid4().hex[:8]}@example.com", "Sarah Chen")
        _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")

        count = rule_linkedin_correlation(cur)

        assert count == 0

    def test_score_is_always_below_rule4s_band(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")

        rule_linkedin_correlation(cur)

        cur.execute(
            "select score from link_candidate where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )
        assert cur.fetchone()[0] < 0.8  # Rule 4's fixed score

    def test_rejected_pair_is_not_re_proposed(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        outlook_id = _make_identity(cur, "outlook", f"eric-{uuid.uuid4().hex[:8]}@example.com", "Eric Tham")
        conn_id = _make_linkedin_connection(cur, "Eric", "Tham", company="Acme")
        rule_linkedin_correlation(cur)
        cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        linkedin_identity_id = cur.fetchone()[0]
        cur.execute(
            "update link_candidate set status = 'rejected' where identity_a_id = %s or identity_b_id = %s",
            (outlook_id, outlook_id),
        )

        count = rule_linkedin_correlation(cur)

        assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_linkedin_correlation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution.linkedin_correlation'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/linkedin_correlation.py
"""Rule 5 of §8's identity-resolution ladder: LinkedIn name + organisation
correlation. Never automatic, always queued for human review — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md.
Phase 1: plain string similarity. Phase 2 (not built yet) scores this
with model assistance instead, still always queued.
"""

from __future__ import annotations

from .safety import has_existing_rejected_candidate

_NAME_MATCH_SCORE = 0.5
_NO_COMPANY_SCORE = 0.3


def _normalise_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def rule_linkedin_correlation(cur) -> int:
    cur.execute("select id, first_name, last_name, company from linkedin_connection")
    connections = cur.fetchall()
    cur.execute(
        "select id, display_name from identity where channel in ('outlook', 'whatsapp') and display_name is not null"
    )
    other_identities = cur.fetchall()

    count = 0
    for connection_id, first_name, last_name, company in connections:
        if not first_name or not last_name:
            continue
        full_name = _normalise_name(f"{first_name} {last_name}")

        for other_id, other_display_name in other_identities:
            if _normalise_name(other_display_name) != full_name:
                continue

            cur.execute(
                "insert into identity (channel, handle, display_name) values ('linkedin', %s, %s) on conflict (channel, handle) do nothing",
                (connection_id, f"{first_name} {last_name}".strip()),
            )
            cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (connection_id,))
            linkedin_identity_id = str(cur.fetchone()[0])
            other_identity_id = str(other_id)

            if has_existing_rejected_candidate(cur, linkedin_identity_id, other_identity_id):
                continue

            score = _NAME_MATCH_SCORE if company else _NO_COMPANY_SCORE
            reason = (
                f"LinkedIn '{first_name} {last_name}'"
                + (f" @ {company}" if company else "")
                + f" vs '{other_display_name}' — exact normalised name match"
            )
            cur.execute(
                """
                insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason)
                values (%s, %s, %s, 'linkedin_name_company', 'pending', %s)
                """,
                (linkedin_identity_id, other_identity_id, score, reason),
            )
            count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_linkedin_correlation.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/linkedin_correlation.py tests/test_resolution_linkedin_correlation.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/linkedin_correlation.py tests/test_resolution_linkedin_correlation.py
git commit -m "Add Rule 5: LinkedIn name + organisation correlation, always queued for review"
```

---

### Task 9: Structured knowledge-graph facts from LinkedIn connections

**Files:**
- Create: `adapters/resolution/structured_facts.py`
- Test: `tests/test_resolution_structured_facts.py`

**Interfaces:**
- Consumes: `adapters.resolution.organizations.get_or_create_organization`.
- Produces (used by Task 10's `run.py`): `extract_structured_facts(cur) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolution_structured_facts.py
from __future__ import annotations

import uuid

import psycopg

from adapters.resolution.structured_facts import extract_structured_facts


def _make_linkedin_connection(cur, first_name: str = "Eric", last_name: str = "Tham", company: str | None = None, position: str | None = None) -> str:
    conn_id = f"https://linkedin.com/in/{uuid.uuid4().hex[:10]}"
    cur.execute(
        "insert into linkedin_connection (id, first_name, last_name, company, position) values (%s, %s, %s, %s, %s)",
        (conn_id, first_name, last_name, company, position),
    )
    return conn_id


class TestExtractStructuredFacts:
    def test_company_produces_a_works_at_fact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        conn_id = _make_linkedin_connection(cur, company="Acme Inc")

        count = extract_structured_facts(cur)

        assert count >= 1
        cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        identity_id = cur.fetchone()[0]
        cur.execute(
            "select fact_type, object_org_id, confidence, status, source from fact where subject_identity_id = %s and fact_type = 'works_at'",
            (identity_id,),
        )
        fact_type, org_id, confidence, status, source = cur.fetchone()
        assert fact_type == "works_at"
        assert org_id is not None
        assert confidence == 1.0
        assert status == "confirmed"  # structured-source facts are high-confidence, not a guess
        assert source == "linkedin_connection"

    def test_position_produces_a_has_title_fact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        conn_id = _make_linkedin_connection(cur, position="Data Lead")

        extract_structured_facts(cur)

        cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (conn_id,))
        identity_id = cur.fetchone()[0]
        cur.execute(
            "select object_text from fact where subject_identity_id = %s and fact_type = 'has_title'",
            (identity_id,),
        )
        assert cur.fetchone()[0] == "Data Lead"

    def test_missing_company_and_position_produce_no_facts(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_linkedin_connection(cur, company=None, position=None)

        count = extract_structured_facts(cur)

        assert count == 0

    def test_rerun_does_not_duplicate_facts(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_linkedin_connection(cur, company="Acme Inc")

        first_count = extract_structured_facts(cur)
        second_count = extract_structured_facts(cur)

        assert first_count == 1
        assert second_count == 0

    def test_company_variant_reuses_the_same_organization(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        _make_linkedin_connection(cur, first_name="Eric", last_name="Tham", company="Acme Inc")
        _make_linkedin_connection(cur, first_name="Sarah", last_name="Chen", company="Acme")

        extract_structured_facts(cur)

        cur.execute("select object_org_id from fact where fact_type = 'works_at'")
        org_ids = {row[0] for row in cur.fetchall()}
        assert len(org_ids) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_structured_facts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution.structured_facts'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/structured_facts.py
"""Knowledge-graph facts from structured sources that are already fully
ingested and need no model call — Phase 1 of the §10 knowledge-graph
upgrade. See
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
Scope item 7.
"""

from __future__ import annotations

from .organizations import get_or_create_organization


def _get_or_create_linkedin_identity(cur, connection_id: str) -> str:
    cur.execute(
        "insert into identity (channel, handle) values ('linkedin', %s) on conflict (channel, handle) do nothing",
        (connection_id,),
    )
    cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (connection_id,))
    return str(cur.fetchone()[0])


def extract_structured_facts(cur) -> int:
    cur.execute("select id, company, position from linkedin_connection")
    connections = cur.fetchall()
    count = 0
    for connection_id, company, position in connections:
        identity_id = _get_or_create_linkedin_identity(cur, connection_id)

        if company:
            org_id = get_or_create_organization(cur, company)
            cur.execute(
                "select 1 from fact where subject_identity_id = %s and fact_type = 'works_at' and object_org_id = %s",
                (identity_id, org_id),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    insert into fact
                        (subject_identity_id, fact_type, object_org_id, confidence, source, status)
                    values (%s, 'works_at', %s, 1.0, 'linkedin_connection', 'confirmed')
                    """,
                    (identity_id, org_id),
                )
                count += 1

        if position:
            cur.execute(
                "select 1 from fact where subject_identity_id = %s and fact_type = 'has_title' and object_text = %s",
                (identity_id, position),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    insert into fact
                        (subject_identity_id, fact_type, object_text, confidence, source, status)
                    values (%s, 'has_title', %s, 1.0, 'linkedin_connection', 'confirmed')
                    """,
                    (identity_id, position),
                )
                count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_structured_facts.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/structured_facts.py tests/test_resolution_structured_facts.py`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/structured_facts.py tests/test_resolution_structured_facts.py
git commit -m "Add structured knowledge-graph facts (WORKS_AT/HAS_TITLE) from LinkedIn connections"
```

---

### Task 10: Entrypoint — `adapters/resolution/run.py`

**Files:**
- Create: `adapters/resolution/run.py`
- Test: `tests/test_resolution_run.py`

**Interfaces:**
- Consumes: `rule_exact_email_match`, `rule_contact_bridge` (Rule 2 folded into Rule 3, per Task 6), `rule_signature_phone`, `rule_linkedin_correlation`, `extract_structured_facts`.
- Produces: `run() -> None` (CLI entrypoint, `python -m adapters.resolution.run`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolution_run.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from adapters.resolution.run import run


def test_run_calls_every_rule_and_structured_facts(monkeypatch):
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_cursor = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

    with patch("adapters.resolution.run.psycopg.connect", return_value=fake_conn), \
         patch("adapters.resolution.run.rule_exact_email_match", return_value=0) as m1, \
         patch("adapters.resolution.run.rule_contact_bridge", return_value=0) as m2, \
         patch("adapters.resolution.run.rule_signature_phone", return_value=0) as m3, \
         patch("adapters.resolution.run.rule_linkedin_correlation", return_value=0) as m4, \
         patch("adapters.resolution.run.extract_structured_facts", return_value=0) as m5, \
         patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
        run()

    m1.assert_called_once()
    m2.assert_called_once()
    m3.assert_called_once()
    m4.assert_called_once()
    m5.assert_called_once()


def test_run_survives_one_rule_raising(monkeypatch, capsys):
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_cursor = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

    with patch("adapters.resolution.run.psycopg.connect", return_value=fake_conn), \
         patch("adapters.resolution.run.rule_exact_email_match", side_effect=RuntimeError("boom")), \
         patch("adapters.resolution.run.rule_contact_bridge", return_value=0) as m2, \
         patch("adapters.resolution.run.rule_signature_phone", return_value=0), \
         patch("adapters.resolution.run.rule_linkedin_correlation", return_value=0), \
         patch("adapters.resolution.run.extract_structured_facts", return_value=0), \
         patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
        run()  # must not raise

    m2.assert_called_once()  # the rule after the failing one still ran
    assert "boom" in capsys.readouterr().err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.resolution.run'`

- [ ] **Step 3: Write the implementation**

```python
# adapters/resolution/run.py
"""Entrypoint for identity resolution + Phase 1 structured knowledge-graph
facts. Run: python -m adapters.resolution.run

Deliberately manual, not scheduled — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
"Architecture".
"""

from __future__ import annotations

import os
import sys

import psycopg
from dotenv import load_dotenv

from .linkedin_correlation import rule_linkedin_correlation
from .rules import rule_contact_bridge, rule_exact_email_match, rule_signature_phone
from .structured_facts import extract_structured_facts


def run() -> None:
    # built inside the function, not at module scope — a module-level
    # list would capture these function objects once at import time,
    # and a test patching e.g. "adapters.resolution.run.rule_exact_email_match"
    # afterward would never reach it (the patch replaces the module
    # attribute, not the reference already stored in the list), so the
    # rule functions must be looked up fresh on every call
    rules = [
        ("exact email match", rule_exact_email_match),
        ("contact bridge", rule_contact_bridge),
        ("signature phone", rule_signature_phone),
        ("LinkedIn name+company correlation", rule_linkedin_correlation),
        ("structured facts", extract_structured_facts),
    ]

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            for label, rule_fn in rules:
                try:
                    count = rule_fn(cur)
                    conn.commit()
                    print(f"{label}: {count}")
                except Exception as e:  # noqa: BLE001 — one rule's bug must not block the rest
                    conn.rollback()
                    print(f"{label}: FAILED — {e}", file=sys.stderr)


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resolution_run.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite, lint, and a real end-to-end check**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check adapters/resolution/run.py tests/test_resolution_run.py`
Expected: all pass, no lint errors

Then run for real against this project's actual database:
Run: `.venv/Scripts/python.exe -m adapters.resolution.run`
Expected: prints a count per rule; no rule prints FAILED. Rules touching
`graph_contact` (contact bridge) print `0` (real, expected — see the
design doc's Known real-data limitation). Rule 1 (exact email) and Rule
5 (LinkedIn correlation) may find real candidates given this project's
actual LinkedIn connections data — inspect what they found:
```bash
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms -c "select method, status, reason from link_candidate order by score desc limit 20"
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms -c "select fact_type, object_text, object_org_id, status from fact limit 20"
```
Read the actual output — do these look like real, sensible candidates,
or did something match on garbage? Note anything surprising in the
commit message.

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/run.py tests/test_resolution_run.py
git commit -m "Add adapters.resolution.run entrypoint, running all Phase 1 rules"
```

---

### Task 11: Review queue in the ops dashboard

**Files:**
- Modify: `scripts/onboarding/app.py`
- Create: `scripts/onboarding/templates/resolution.html`
- Modify: `scripts/onboarding/templates/index.html` (add a link to the new page)
- Test: `tests/test_onboarding_app.py` (extend)

**Interfaces:**
- Consumes: `adapters.resolution.merge.apply_merge`.
- Produces: `GET /resolution`, `POST /resolution/candidate/<id>/confirm`, `POST /resolution/candidate/<id>/reject`, `POST /resolution/fact/<id>/confirm`, `POST /resolution/fact/<id>/reject` routes on the existing Flask app from `scripts/onboarding/app.py`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_onboarding_app.py
import uuid as _uuid

# same local Postgres URL tests/conftest.py's db_conn fixture uses,
# deliberately hardcoded there (not read from .env) because .env's
# DATABASE_URL points at the real hosted Supabase project — this file's
# resolution routes each open their OWN fresh connection via
# _get_status_cursor(), which reads os.environ["DATABASE_URL"] directly.
# Without redirecting that env var for the duration of these tests, every
# route call below would silently connect to and mutate the real
# production database instead of the local db_conn fixture's Postgres,
# while the test's own seeded rows (via db_conn) would sit in a
# completely separate database the route never sees. Caught by hand-
# tracing this exact mismatch before dispatch — not a hypothetical.
_RESOLUTION_TEST_DATABASE_URL = "postgresql://comms:comms@localhost:5432/comms"


class TestResolutionReviewQueue:
    @pytest.fixture(autouse=True)
    def _routes_use_local_db(self, monkeypatch):
        # autouse + defined inside the class, so this only wraps tests in
        # THIS class — every other test in the file is unaffected.
        monkeypatch.setenv("DATABASE_URL", _RESOLUTION_TEST_DATABASE_URL)

    def test_get_resolution_candidates_json_lists_pending(self, db_conn):
        # the /resolution page itself renders client-side (fetches
        # candidates.json via JS, see the template in Step 3) — assert on
        # the JSON endpoint directly rather than the initial HTML, which
        # never contains "test reason" verbatim
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle, display_name) values ('outlook', %s, 'Eric Tham') returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle, display_name) values ('whatsapp', %s, 'Eric') returning id", (b_handle,))
        b = cur.fetchone()[0]
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason) values (%s, %s, 0.5, 'test', 'pending', 'test reason')",
            (a, b),
        )
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.get("/resolution/candidates.json")

        assert resp.status_code == 200
        body = resp.get_json()
        assert any(item["reason"] == "test reason" for item in body)

    def test_confirm_candidate_applies_the_merge(self, db_conn):
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle, display_name) values ('outlook', %s, 'Eric Tham') returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle, display_name) values ('whatsapp', %s, 'Eric') returning id", (b_handle,))
        b = cur.fetchone()[0]
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) values (%s, %s, 0.5, 'test', 'pending') returning id",
            (a, b),
        )
        candidate_id = cur.fetchone()[0]
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.post(f"/resolution/candidate/{candidate_id}/confirm")

        assert resp.status_code == 200
        cur.execute("select person_id from identity where id = %s", (a,))
        assert cur.fetchone()[0] is not None
        cur.execute("select status from link_candidate where id = %s", (candidate_id,))
        assert cur.fetchone()[0] == "confirmed"

    def test_reject_candidate_does_not_merge(self, db_conn):
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle) values ('outlook', %s) returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle) values ('whatsapp', %s) returning id", (b_handle,))
        b = cur.fetchone()[0]
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) values (%s, %s, 0.5, 'test', 'pending') returning id",
            (a, b),
        )
        candidate_id = cur.fetchone()[0]
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.post(f"/resolution/candidate/{candidate_id}/reject")

        assert resp.status_code == 200
        cur.execute("select status from link_candidate where id = %s", (candidate_id,))
        assert cur.fetchone()[0] == "rejected"
        cur.execute("select person_id from identity where id = %s", (a,))
        assert cur.fetchone()[0] is None

    def test_confirm_is_a_no_op_on_a_non_pending_candidate(self, db_conn):
        cur = db_conn.cursor()
        a_email = f"a-{_uuid.uuid4().hex}@example.com"
        b_handle = f"{_uuid.uuid4().hex[:10]}@s.whatsapp.net"
        cur.execute("insert into identity (channel, handle) values ('outlook', %s) returning id", (a_email,))
        a = cur.fetchone()[0]
        cur.execute("insert into identity (channel, handle) values ('whatsapp', %s) returning id", (b_handle,))
        b = cur.fetchone()[0]
        cur.execute(
            "insert into link_candidate (identity_a_id, identity_b_id, score, method, status) values (%s, %s, 0.5, 'test', 'rejected') returning id",
            (a, b),
        )
        candidate_id = cur.fetchone()[0]
        db_conn.commit()

        flask_app = onboarding_app.create_app(testing=True)
        client = flask_app.test_client()
        resp = client.post(f"/resolution/candidate/{candidate_id}/confirm")

        assert resp.status_code == 200
        cur.execute("select status from link_candidate where id = %s", (candidate_id,))
        assert cur.fetchone()[0] == "rejected"  # unchanged, not flipped to confirmed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -k Resolution -v`
Expected: FAIL with 404s (routes don't exist)

- [ ] **Step 3: Write the template**

```html
<!-- scripts/onboarding/templates/resolution.html -->
<!DOCTYPE html>
<html>
<head>
  <title>Comms Platform — Review Queue</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; }
    .item { border: 1px solid #ccc; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
    .item .score { font-weight: 600; color: #a8791f; }
    .item .reason { color: #4c525d; margin: 8px 0; }
    .item .names { font-size: 1.1em; margin-bottom: 4px; }
    button { padding: 6px 14px; margin-right: 8px; cursor: pointer; }
    .confirm { background: #e2f1e8; border: 1px solid #2f8f5b; }
    .reject { background: #f7e5e3; border: 1px solid #b1453c; }
  </style>
</head>
<body>
  <h1>Review queue</h1>
  <p>Pending identity matches and knowledge-graph facts — confirm the ones that are right, reject the ones that aren't.</p>

  <h2>Identity matches</h2>
  <div id="candidates">Loading…</div>

  <h2>Facts</h2>
  <div id="facts">Loading…</div>

<script>
async function loadCandidates() {
  const resp = await fetch("/resolution/candidates.json");
  const items = await resp.json();
  const container = document.getElementById("candidates");
  if (items.length === 0) {
    container.textContent = "Nothing pending.";
    return;
  }
  container.innerHTML = items.map(item => `
    <div class="item">
      <div class="names">${item.name_a} (${item.channel_a}) &harr; ${item.name_b} (${item.channel_b})</div>
      <div class="score">score ${item.score.toFixed(2)} — ${item.method}</div>
      <div class="reason">${item.reason || ""}</div>
      <button class="confirm" onclick="act('candidate', ${item.id}, 'confirm')">Confirm — same person</button>
      <button class="reject" onclick="act('candidate', ${item.id}, 'reject')">Reject — different people</button>
    </div>
  `).join("");
}

async function loadFacts() {
  const resp = await fetch("/resolution/facts.json");
  const items = await resp.json();
  const container = document.getElementById("facts");
  if (items.length === 0) {
    container.textContent = "Nothing pending.";
    return;
  }
  container.innerHTML = items.map(item => `
    <div class="item">
      <div class="names">${item.subject_name} — ${item.fact_type} — ${item.object_display}</div>
      <div class="score">confidence ${item.confidence.toFixed(2)} — ${item.source}</div>
      <div class="reason">${item.reason || ""}</div>
      <button class="confirm" onclick="act('fact', ${item.id}, 'confirm')">Confirm</button>
      <button class="reject" onclick="act('fact', ${item.id}, 'reject')">Reject</button>
    </div>
  `).join("");
}

async function act(kind, id, action) {
  await fetch(`/resolution/${kind}/${id}/${action}`, { method: "POST" });
  loadCandidates();
  loadFacts();
}

loadCandidates();
loadFacts();
</script>
</body>
</html>
```

- [ ] **Step 4: Write the routes**

Add to `scripts/onboarding/app.py`, near the other imports:

```python
from adapters.resolution.merge import apply_merge
```

Add inside `create_app`, after the LinkedIn routes:

```python
    @flask_app.get("/resolution")
    def resolution_page():
        return render_template("resolution.html")

    @flask_app.get("/resolution/candidates.json")
    def resolution_candidates_json():
        cur = _get_status_cursor()
        try:
            cur.execute(
                """
                select lc.id, lc.score, lc.method, lc.reason,
                       ia.display_name, ia.channel, ib.display_name, ib.channel
                from link_candidate lc
                join identity ia on ia.id = lc.identity_a_id
                join identity ib on ib.id = lc.identity_b_id
                where lc.status = 'pending'
                order by lc.score desc
                """
            )
            rows = cur.fetchall()
        finally:
            cur.connection.close()
        return jsonify([
            {
                "id": r[0], "score": r[1], "method": r[2], "reason": r[3],
                "name_a": r[4] or "(no name)", "channel_a": r[5],
                "name_b": r[6] or "(no name)", "channel_b": r[7],
            }
            for r in rows
        ])

    @flask_app.post("/resolution/candidate/<candidate_id>/confirm")
    def resolution_candidate_confirm(candidate_id):
        cur = _get_status_cursor()
        try:
            cur.execute("select identity_a_id, identity_b_id, status from link_candidate where id = %s", (candidate_id,))
            row = cur.fetchone()
            if row is None or row[2] != "pending":
                return jsonify({"status": "no_op"})
            identity_a_id, identity_b_id, _ = row
            apply_merge(cur, str(identity_a_id), str(identity_b_id))
            cur.execute("update link_candidate set status = 'confirmed', reviewed_at = now() where id = %s", (candidate_id,))
            cur.connection.commit()
        finally:
            cur.connection.close()
        return jsonify({"status": "confirmed"})

    @flask_app.post("/resolution/candidate/<candidate_id>/reject")
    def resolution_candidate_reject(candidate_id):
        cur = _get_status_cursor()
        try:
            cur.execute("update link_candidate set status = 'rejected' where id = %s and status = 'pending'", (candidate_id,))
            cur.connection.commit()
        finally:
            cur.connection.close()
        return jsonify({"status": "rejected"})

    @flask_app.get("/resolution/facts.json")
    def resolution_facts_json():
        cur = _get_status_cursor()
        try:
            cur.execute(
                """
                select f.id, f.fact_type, f.confidence, f.source, f.reason,
                       i.display_name, f.object_text, o.canonical_name
                from fact f
                join identity i on i.id = f.subject_identity_id
                left join organization o on o.id = f.object_org_id
                where f.status = 'pending'
                order by f.confidence desc
                """
            )
            rows = cur.fetchall()
        finally:
            cur.connection.close()
        return jsonify([
            {
                "id": r[0], "fact_type": r[1], "confidence": r[2], "source": r[3], "reason": r[4],
                "subject_name": r[5] or "(no name)",
                "object_display": r[7] or r[6] or "(unknown)",
            }
            for r in rows
        ])

    @flask_app.post("/resolution/fact/<fact_id>/confirm")
    def resolution_fact_confirm(fact_id):
        cur = _get_status_cursor()
        try:
            cur.execute("update fact set status = 'confirmed', reviewed_at = now() where id = %s and status = 'pending'", (fact_id,))
            cur.connection.commit()
        finally:
            cur.connection.close()
        return jsonify({"status": "confirmed"})

    @flask_app.post("/resolution/fact/<fact_id>/reject")
    def resolution_fact_reject(fact_id):
        cur = _get_status_cursor()
        try:
            cur.execute("update fact set status = 'rejected', reviewed_at = now() where id = %s and status = 'pending'", (fact_id,))
            cur.connection.commit()
        finally:
            cur.connection.close()
        return jsonify({"status": "rejected"})
```

- [ ] **Step 5: Add a link from the main dashboard page**

In `scripts/onboarding/templates/index.html`, add near the top (after the
`<h1>`):

```html
<p><a href="/resolution">Review queue →</a></p>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -k Resolution -v`
Expected: PASS (4 tests: json-listing, confirm, reject, no-op-on-non-pending)

- [ ] **Step 7: Run the full suite, lint, and a real manual check**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check scripts/onboarding/`
Expected: all pass, no lint errors

Then start the dashboard for real and check the page renders:
Run: `.venv/Scripts/python.exe scripts/onboarding/app.py` (background), then
`curl http://localhost:5000/resolution/candidates.json` and `curl
http://localhost:5000/resolution/facts.json` — expected: valid JSON
arrays, reflecting whatever Task 10's real run against this project's
database produced. Stop the process afterward.

- [ ] **Step 8: Commit**

```bash
git add scripts/onboarding/app.py scripts/onboarding/templates/resolution.html scripts/onboarding/templates/index.html tests/test_onboarding_app.py
git commit -m "Add identity/fact review queue to the ops dashboard"
```

---

## Self-Review Notes

- **Spec coverage:** Rule 1 → Task 6, Rule 2 → folded into Rule 3 per the 2026-09-03 decision with Eva (a phone-only match has no identity to merge into on its own; weaker evidence than the other automatic rules anyway), Rule 3 → Task 6, Rule 4 → Task 7, Rule 5 → Task 8, Rule 6 → unresolved (per spec). Safety checks 1-5 → Task 2, applied inside Task 6-8's rules. Evidence provenance (`reason`) → Task 2/6/7/8's `reason` columns. `fact`/`organization` schema → Task 1, populated by Task 9. Naming → Task 3, applied by Task 5. Review queue → Task 11. Adversarial tests from the design's Testing section → covered across Task 6 (generic address, recycled number, contact-bridge false-negative), Task 4 (organization normalisation, including the Acme Inc/Commonwealth Bank cases), Task 2 (name contradiction, rejection durability, cluster size) — transitive A-B-C over-merge and "two similarly-named LinkedIn profiles" are **not yet covered by an explicit test** in this plan; flagging this as a gap the implementer should close by adding a test in Task 6 or Task 8 covering the transitive case (confirm A-B, confirm B-C, verify A and C ended up correctly merged or not per real safety-check behavior — this needs runtime verification, not just a design assertion, since the plan's own rules don't have explicit anti-transitivity logic beyond what safety checks 2/5 incidentally catch).
- **Placeholder scan:** none of the "TBD/TODO" patterns found. Rule 2's original open design question (was a STOP block in an earlier draft of this plan) is resolved — see Task 6's header note — and no placeholder remains in its place.
- **Type consistency:** `link_candidate.reason`, `fact.reason` used consistently from Task 1 onward. `apply_merge(cur, identity_a_id: str, identity_b_id: str) -> str` signature matches between Task 5's definition, Task 6's usage, and Task 11's route usage. `MAX_CLUSTER_SIZE` imported consistently in Task 6 from `safety.py`. `rule_exact_phone_match` does not appear anywhere in the plan (verified via grep after the Task 6 rewrite) — Task 9's `run.py` imports only `rule_exact_email_match`, `rule_contact_bridge`, `rule_signature_phone`, `rule_linkedin_correlation`, `extract_structured_facts`.
