## 1. Schema

- [x] 1.1 Add migration `db/migrations/0006_merge_log.sql` creating
      `merge_log` (id, merged_at, identity_a_id, identity_b_id,
      survivor_person_id, absorbed_person_id nullable, moved_identity_ids
      uuid[] nullable, prev_primary_name, prev_preferred_name nullable,
      reversed_at nullable) with FKs to `identity`/`person` and an index on
      `survivor_person_id`. (Built as `text[]` not `uuid[]`, and
      `merged_at` defaults to `clock_timestamp()` not `now()` — see 3.1's
      note.)

## 2. apply_merge logging

- [x] 2.1 In `adapters/resolution/merge.py`, before any mutation, read the
      survivor's current `primary_name`/`preferred_name` and, for the
      cluster-union case, the full list of identity ids currently under the
      absorbed person. (Generalized during implementation: `moved_identity_ids`
      is now computed for all three cases, not just cluster-union — see
      the design doc's "moved_identity_ids is populated for all three
      cases" correction.)
- [x] 2.2 Insert the `merge_log` row with that captured state (see
      design.md's field mapping) before the existing update statements run,
      in the same transaction/cursor.
- [x] 2.3 Superseded: no signature change needed. Checked both callers —
      neither `rules.py:77` nor `app.py:364` uses `apply_merge`'s return
      value, so there's no reason to add a second return value; `undo_merge`
      looks up `merge_log` rows by querying the table directly instead.

## 3. undo_merge

- [x] 3.1 Implement `undo_merge(cur, merge_log_id)` in
      `adapters/resolution/merge.py`: look up the log row, check for a later
      `merge_log` row with the same `survivor_person_id`, raise if found.
      (Real bug caught by the TDD test for this: `merge_log.merged_at`
      originally defaulted to `now()`, which is frozen for the whole
      transaction — two merges in one transaction got an identical
      timestamp and the "later than" check could never fire. Fixed by
      switching the column default to `clock_timestamp()`.)
- [x] 3.2 If clear, move `moved_identity_ids` back to `absorbed_person_id`,
      clear its `merged_into`, restore the survivor's name fields, stamp
      `reversed_at`.
- [x] 3.3 Handle the case-1/2 log rows (no `absorbed_person_id`) — same
      code path as 3.2: `moved_identity_ids` is populated for these cases
      too (see 2.1's note), so undo moves them to `null` (no person)
      instead of to `absorbed_person_id`, using the exact same "if
      absorbed_person_id is not None" branch.

## 4. Tests

- [x] 4.1 Extend `tests/test_resolution_merge.py`: cluster-union merge writes
      a `merge_log` row with the correct `moved_identity_ids` and prior name.
- [x] 4.2 Test `undo_merge` fully reverses a cluster-union merge: identities
      move back, `merged_into` clears, name restores, `reversed_at` is set.
- [x] 4.3 Test `undo_merge` raises and makes no changes when a later merge
      touched the same survivor.
- [x] 4.4 Test logging for the case-1 and case-2 merge paths (no absorbed
      person), plus undo for both.

## 5. Wrap-up

- [x] 5.1 Ran the full test suite (166 passed). One real regression found
      and fixed along the way: `tests/test_onboarding_app.py`'s
      `TestResolutionReviewQueue._created_identity_ids` fixture manually
      deletes `identity` rows it committed during the test (needed since
      those tests commit for real, for the Flask route's own connection to
      see them) — `merge_log`'s new FK on `identity` made that delete fail
      with a `ForeignKeyViolation` whenever the test's confirmed merge
      logged a row. Fixed by also deleting the referencing `merge_log` rows
      in that same cleanup.
- [ ] 5.2 Run `openspec archive reversible-identity-merge` once Eva has
      reviewed the implementation, syncing `specs/identity-merge-audit/spec.md`
      into `openspec/specs/`.
