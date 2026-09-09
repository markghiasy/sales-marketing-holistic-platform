# Reversible Identity Merge + Merge Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make identity-merge cluster unions reversible and auditable: log
enough state before every `apply_merge` call to undo it exactly, and add
`undo_merge` to actually reverse one.

**Architecture:** A new `merge_log` table records, per `apply_merge` call,
the identity ids that moved, the survivor's prior name, and merge
provenance. `apply_merge` writes one row before mutating anything.
`undo_merge(cur, merge_log_id)` reads that row and applies the exact
inverse, refusing if a later merge already touched the same survivor person.

**Tech Stack:** Python, psycopg (v3), PostgreSQL, pytest.

## Global Constraints

- Every SQL statement lives inline in `adapters/resolution/merge.py`, matching this file's existing style — no query builder, no ORM.
- Migrations are forward-only, numbered sequentially in `db/migrations/`, and applied to the local dev Postgres by hand for an already-initialized volume (`docker-entrypoint-initdb.d` only runs on a fresh volume).
- Tests use the `db_conn` fixture from `tests/conftest.py` (local docker-compose Postgres, transaction rolled back at teardown, never committed) — never touch the hosted Supabase instance.
- Identity and person ids are handled as `str` throughout the Python layer (existing convention in `merge.py`/`test_resolution_merge.py`), even though the underlying columns are `uuid`.
- `apply_merge`'s existing return type (`str`, the survivor person id) does not change — neither of its two callers (`adapters/resolution/rules.py:77`, `scripts/onboarding/app.py:364`) uses the return value, so there is no reason to add a second return value for the new log id; `undo_merge` looks up merge_log rows by querying the table directly.

---

### Task 1: Migration — `merge_log` table

**Files:**
- Create: `db/migrations/0006_merge_log.sql`

**Interfaces:**
- Produces: table `merge_log` (columns below) — every later task depends on this migration having run against the local dev database.

- [ ] **Step 1: Write the migration**

```sql
-- db/migrations/0006_merge_log.sql
-- Reversible identity merge + merge audit log.
-- See docs/superpowers/specs/2026-09-09-reversible-identity-merge-design.md.

create table merge_log (
    id                   uuid primary key default gen_random_uuid(),
    merged_at            timestamptz not null default now(),
    identity_a_id        uuid not null references identity(id),
    identity_b_id        uuid not null references identity(id),
    survivor_person_id   uuid not null references person(id),
    absorbed_person_id   uuid references person(id),        -- null unless this
                                                              -- merge folded a
                                                              -- second, already-
                                                              -- resolved cluster
                                                              -- into the survivor
    moved_identity_ids   text[] not null,                    -- every identity id
                                                              -- whose person_id
                                                              -- changed to
                                                              -- survivor_person_id
                                                              -- as a result of
                                                              -- this merge
    prev_primary_name    text not null,                      -- survivor's name
                                                              -- before this merge's
                                                              -- naming recompute
    prev_preferred_name  text,
    reversed_at          timestamptz                         -- null until undone
);

create index on merge_log (survivor_person_id);
```

- [ ] **Step 2: Apply it to the local dev database and verify**

Run: `docker compose up -d` (if not already running), then:
```bash
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms < db/migrations/0006_merge_log.sql
```
Expected: no errors. Then verify:
```bash
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms -c "\d merge_log"
```
Expected: `merge_log` listed with all nine columns above, `id` primary key, an index on `survivor_person_id`.

- [ ] **Step 3: Commit**

```bash
git add db/migrations/0006_merge_log.sql
git commit -m "Add merge_log table for reversible identity merges"
```

---

### Task 2: `apply_merge` computes and logs `moved_identity_ids`

**Files:**
- Modify: `adapters/resolution/merge.py`
- Test: `tests/test_resolution_merge.py`

**Interfaces:**
- Consumes: `merge_log` table (Task 1).
- Produces: `apply_merge(cur, identity_a_id: str, identity_b_id: str) -> str` — unchanged signature and return value; now also inserts one `merge_log` row per call. Later tasks (`undo_merge`) query `merge_log` directly by `survivor_person_id` or `id`.

This task covers all three merge cases in one change, since the logging
logic is one code path with a shared shape — a case-3 identity list, a
case-1/2 identity list, or a single case-2 identity, all reduced to the same
`moved_identity_ids` list before one shared `insert into merge_log`.

- [ ] **Step 1: Write the three failing tests**

Add to `tests/test_resolution_merge.py`, inside `class TestApplyMerge`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_resolution_merge.py -v -k "logs"`
Expected: all three FAIL — `relation "merge_log"` exists (Task 1 already applied it) but `apply_merge` never writes to it, so each `cur.fetchone()` returns `None` and the `assert row is not None` (or the tuple-unpack of `None`) fails.

- [ ] **Step 3: Rewrite `apply_merge` to compute `moved_identity_ids` and log**

Replace the full contents of `adapters/resolution/merge.py`:

```python
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
```

Note the `person_id` comparison in the case-1/2 branch: `person_a`/`person_b`
are whatever `cur.fetchone()` returned for the `person_id` column — `None`
when unset, or the `uuid.UUID` object psycopg returns for a `uuid` column.
`existing_person != person_id` therefore compares two `uuid.UUID` values (or
`None` against one) correctly; `identity_a_id`/`identity_b_id` themselves
are the `str` ids passed in by the caller, appended to `moved_identity_ids`
as-is, matching the `str` convention the rest of this module already uses.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_resolution_merge.py -v`
Expected: PASS — all 8 tests in `TestApplyMerge` (the original 5 plus the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add adapters/resolution/merge.py tests/test_resolution_merge.py
git commit -m "Log every identity merge to merge_log before mutating"
```

---

### Task 3: `undo_merge` — reverse a cluster-union merge

**Files:**
- Modify: `adapters/resolution/merge.py`
- Test: `tests/test_resolution_merge.py`

**Interfaces:**
- Consumes: `merge_log` rows written by Task 2's `apply_merge`.
- Produces: `undo_merge(cur, merge_log_id: str) -> None`, raising `MergeConflictError` (already defined in Task 2) when a later merge blocks the undo. Task 4 adds the conflict check; this task builds the reversal itself first, unblocked (no later merge exists yet in these tests).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_resolution_merge.py`, as a new class after `TestApplyMerge`:

```python
from adapters.resolution.merge import MergeConflictError, apply_merge, undo_merge


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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_resolution_merge.py -v -k test_undoing_a_cluster_union_merge_restores_both_clusters`
Expected: FAIL with `ImportError: cannot import name 'undo_merge'`.

- [ ] **Step 3: Implement `undo_merge` (no conflict check yet)**

Append to `adapters/resolution/merge.py`:

```python
def undo_merge(cur, merge_log_id: str) -> None:
    cur.execute(
        """
        select absorbed_person_id, moved_identity_ids, prev_primary_name, prev_preferred_name,
               survivor_person_id
        from merge_log
        where id = %s
        """,
        (merge_log_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no merge_log row with id {merge_log_id}")
    absorbed_person_id, moved_identity_ids, prev_primary_name, prev_preferred_name, survivor_person_id = row

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
```

`absorbed_person_id` is `None` for a case-1/2 merge, and `update identity
set person_id = null where ...` is valid SQL — this same branch already
handles the case-1/2 "detach back to no person" behavior Task 5 tests
explicitly; Task 3 only exercises the case-3 (non-null) path.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_resolution_merge.py -v -k test_undoing_a_cluster_union_merge_restores_both_clusters`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add adapters/resolution/merge.py tests/test_resolution_merge.py
git commit -m "Add undo_merge to reverse a logged identity merge"
```

---

### Task 4: `undo_merge` refuses when a later merge touched the same survivor

**Files:**
- Modify: `adapters/resolution/merge.py`
- Test: `tests/test_resolution_merge.py`

**Interfaces:**
- Consumes: `undo_merge` (Task 3), `MergeConflictError` (Task 2).
- Produces: `undo_merge` now raises `MergeConflictError` and makes no changes when blocked — no interface change for callers who aren't hitting the conflict case.

- [ ] **Step 1: Write the failing test**

Add to `TestUndoMerge`:

```python
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
```

Add `import pytest` at the top of `tests/test_resolution_merge.py` alongside the existing `import psycopg` if it isn't already imported.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_resolution_merge.py -v -k test_undo_refuses_when_a_later_merge_touched_the_same_survivor`
Expected: FAIL — `undo_merge` proceeds and reverses the merge instead of raising, so the `pytest.raises(MergeConflictError)` block fails.

- [ ] **Step 3: Add the conflict check**

In `adapters/resolution/merge.py`, modify `undo_merge` to check for a later merge before making any change:

```python
def undo_merge(cur, merge_log_id: str) -> None:
    cur.execute(
        """
        select absorbed_person_id, moved_identity_ids, prev_primary_name, prev_preferred_name,
               survivor_person_id, merged_at
        from merge_log
        where id = %s
        """,
        (merge_log_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no merge_log row with id {merge_log_id}")
    (absorbed_person_id, moved_identity_ids, prev_primary_name, prev_preferred_name,
     survivor_person_id, merged_at) = row

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
```

**Known limitation, worth stating plainly rather than leaving implicit:**
this check only catches a later merge that names the *same*
`survivor_person_id`. If the original survivor later becomes the *absorbed*
side of a subsequent merge (i.e. it loses the `person_a`/`person_b`
argument-order coin flip in a later `apply_merge` call), that later merge's
`survivor_person_id` is a different person, and this check won't see it —
though `person.merged_into` on the original survivor would still show it
was absorbed, which is a real, visible trail an operator can check by hand.
Closing that gap fully would mean walking the `merged_into` chain at undo
time, which is more machinery than this build needs today; not attempted
here, consistent with this design's existing "Risks / Trade-offs" section.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_resolution_merge.py -v -k test_undo_refuses_when_a_later_merge_touched_the_same_survivor`
Expected: PASS.

- [ ] **Step 5: Run the full `TestUndoMerge` class to confirm no regression**

Run: `pytest tests/test_resolution_merge.py -v`
Expected: PASS — all tests, including Task 3's.

- [ ] **Step 6: Commit**

```bash
git add adapters/resolution/merge.py tests/test_resolution_merge.py
git commit -m "Refuse undo_merge when a later merge touched the same survivor"
```

---

### Task 5: `undo_merge` for case 1/2 (no absorbed person)

**Files:**
- Test: `tests/test_resolution_merge.py`

**Interfaces:**
- Consumes: `undo_merge` (Tasks 3-4) — no code change expected in this task; it verifies the `absorbed_person_id is None` branch already written in Task 3 behaves correctly for both case 1 and case 2. If either test fails, fix `undo_merge` in `adapters/resolution/merge.py` before proceeding — do not skip ahead with a failing assertion.

- [ ] **Step 1: Write the two tests**

Add to `TestUndoMerge`:

```python
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
```

- [ ] **Step 2: Run both tests**

Run: `pytest tests/test_resolution_merge.py -v -k "test_undoing_a_first_time_merge_detaches_both_identities or test_undoing_a_join_merge_detaches_only_the_identity_that_joined"`
Expected: PASS. If either fails, re-read Task 3's `undo_merge` implementation and fix the `absorbed_person_id is None` branch before moving on — this task's job is to prove that branch, not to write new code for it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_resolution_merge.py
git commit -m "Test undo_merge for the no-absorbed-person cases"
```

---

### Task 6: Full regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS, including `tests/test_resolution_rules.py` and `tests/test_resolution_run.py` (both call `apply_merge` indirectly via the automatic rules) and `tests/test_resolution_naming.py`.

- [ ] **Step 2: Manually confirm the schema on the local dev database**

```bash
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms -c "\d merge_log"
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms -c "select count(*) from merge_log"
```
Expected: table structure matches Task 1; count is `0` unless the resolution rules have been run manually against real data since this migration was applied (not expected as part of this plan).

- [ ] **Step 3: Update the OpenSpec change's tasks.md**

Check off every completed item in `openspec/changes/reversible-identity-merge/tasks.md` to match what this plan actually built (some phrasing differs slightly between the rough task list and this plan's finer-grained tasks — check off by outcome, not by exact wording match).

- [ ] **Step 4: Present for review, then archive**

Once Eva has reviewed the implementation (per this project's standing review-before-archive rule), run `/opsx:archive reversible-identity-merge` (or ask Claude to archive it) to sync `specs/identity-merge-audit/spec.md` into `openspec/specs/`.
