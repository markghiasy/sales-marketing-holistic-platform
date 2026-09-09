# Reversible Identity Merge + Merge Audit Log — Design

**Date:** 2026-09-09
**Status:** Approved by Eva, pending implementation plan

## Problem

`apply_merge` (`adapters/resolution/merge.py`) is the single place that
creates person rows and sets `identity.person_id`, used both by automatic
rules (`adapters/resolution/rules.py`) and the human-confirm route in
`scripts/onboarding/app.py`. It handles three cases based on whether
`identity_a`/`identity_b` already belong to persons:

1. Neither identity has a person yet → a new person is created, both attach.
2. One identity already has a person → the other joins it.
3. Both identities already belong to different, already-merged clusters →
   every identity under the losing cluster is moved to the winning one, and
   the losing `person` row is soft-merged via `person.merged_into` (the
   schema's own comment: "reversible, never delete rows").

Case 3 is not actually reversible today, even though no row is ever deleted.
`person.merged_into` records *that* a merge happened and *where it went*,
not *what* moved or *what was overwritten*: the bulk `update identity set
person_id = ... where person_id = ...` doesn't record which identity ids
were affected, distinct from ones already at the winning person or added by
a later merge, and the naming recompute (`select_names` over the whole
resulting cluster) overwrites `person.primary_name`/`preferred_name` with no
record of the prior value. Eva has committed to Mark that this will be fixed
and that merges will be logged.

## Scope

**In scope:** a `merge_log` table and two functions — `apply_merge` writing
a log row before it mutates anything, and a new `undo_merge` that reverses a
logged merge exactly.

**Not in scope:** no UI or API for triggering undo yet — `undo_merge` is a
function other code (or a maintenance script) calls directly. How a human
triggers it (exposed via `scripts/onboarding/app.py`, or staying a
maintenance-only entry point) is a separate follow-up decision, made once
there's an actual need to trigger one.

## The chained-merge question — decided, not deferred

If merge X folds cluster B into A, then merge Y later folds cluster C into
A, undoing X should not blindly pull B's identities back out — a later rule
run might have derived new evidence connecting something in B to something
in C, or otherwise relied on the cluster containing B's identities. There's
no way to detect that entanglement purely from the log after the fact.

**Decided:** `undo_merge` refuses (clear error, no mutation) if any
`merge_log` row exists with the same `survivor_person_id` and a `merged_at`
later than the merge being undone. Two alternatives were considered and
rejected:

- **Always allow, no check** — simplest, but a later merge could have
  depended on the identities this undo silently removes, producing a
  logically inconsistent state with no warning.
- **Allow, leave cleanup to a human** — avoids building the check, but shifts
  the burden to someone noticing the inconsistency after the fact rather
  than preventing it.

Refusing is the safer default: an operator can still undo the later merge
first, then the earlier one, in order. No case is permanently stuck — the
check only forces a specific order.

## Data model

New table, added in the next migration after
`db/migrations/0005_identity_resolution.sql`:

```
merge_log
  id                    uuid primary key
  merged_at             timestamptz not null default clock_timestamp()  -- not now():
                                                                          -- now() is frozen
                                                                          -- for the whole
                                                                          -- transaction, which
                                                                          -- broke the "later
                                                                          -- merge" check below
                                                                          -- when two merges
                                                                          -- landed in one
                                                                          -- transaction — caught
                                                                          -- by the TDD test for
                                                                          -- exactly that case
  identity_a_id         uuid not null references identity(id)
  identity_b_id         uuid not null references identity(id)
  survivor_person_id    uuid not null references person(id)
  absorbed_person_id    uuid references person(id)         -- null for case 1/2
  moved_identity_ids    uuid[] not null                     -- every identity id
                                                              -- whose person_id is
                                                              -- about to change to
                                                              -- survivor_person_id
                                                              -- as a result of this
                                                              -- call, captured
                                                              -- before mutation
  prev_primary_name     text not null                       -- survivor's name
                                                              -- before select_names()
                                                              -- recomputes it
  prev_preferred_name   text
  reversed_at           timestamptz                         -- null until undone
```

Indexed on `survivor_person_id` (the chained-merge check's lookup key).

**`moved_identity_ids` is populated for all three cases, not just case 3** —
corrected from an earlier draft of this design that tried to recover the
case-1/2 identity from `identity_a_id`/`identity_b_id` directly. That breaks
for case 2 specifically: when one side already has the survivor person and
the other joins it, the two columns are symmetric — nothing distinguishes
"the side that already belonged" from "the side that joined" once other
merges have touched the survivor since. Recording the actual set moved (one
id for case 2, two for case 1, the whole absorbed cluster for case 3) is the
same mechanism in every case, not a special one for case 3.

## Behavior

**`apply_merge`** determines `moved_identity_ids` before making any change:
for case 3, every identity id currently under the absorbed person (about to
be bulk-moved to the survivor); for case 1, both `identity_a_id` and
`identity_b_id` (both new to the freshly-created person); for case 2,
whichever single identity didn't already carry the survivor's person id. It
then reads the survivor's current `primary_name`/`preferred_name`
(post-creation for case 1, so a fresh person's captured "previous" name is
its initial `''`), and writes the `merge_log` row with that captured state,
in the same transaction as the existing mutations, before proceeding exactly
as it does today.

**`undo_merge(cur, merge_log_id)`**:
1. Look up the log row.
2. Check for any other `merge_log` row with the same `survivor_person_id`
   and a later `merged_at`. If found, raise and make no changes.
3. Otherwise: move every id in `moved_identity_ids` to `absorbed_person_id`
   (case 3) or to `null` (cases 1/2 — detaching back to no person; case 1
   leaves the now-empty person row in place, never deleted, matching the
   schema's own "never delete rows" stance). If `absorbed_person_id` is set,
   clear that person's `merged_into`. Restore `primary_name`/
   `preferred_name` on the survivor from `prev_*`. Stamp `reversed_at` on
   the log row.

Logging happens inside the same transaction as the merge mutations, so a
partial failure can't leave a merge applied without a log row, or vice
versa — this falls out naturally since `apply_merge` already runs under one
caller-managed transaction; no extra machinery needed.

## Risks / Trade-offs

- Refusing undo when a later merge touched the same survivor can block a
  legitimate undo even when the later merge is unrelated. Acceptable: the
  operator can always undo the later merge first, in order — no case is
  permanently stuck, just ordered.
- `merge_log` grows unboundedly as merges accumulate. No mitigation planned
  now — merge volume is expected to stay small (cluster consolidation, not a
  high-frequency event); revisit if that assumption breaks.
- Merges applied before this change have no recoverable pre-merge snapshot
  and simply aren't undoable — matches today's reality, no backfill
  attempted.

## Testing

TDD throughout, extending `tests/test_resolution_merge.py`:
- Case 3 merge writes a `merge_log` row with the correct
  `moved_identity_ids` and prior name.
- `undo_merge` fully reverses a case 3 merge: identities move back,
  `merged_into` clears, name restores, `reversed_at` is set.
- `undo_merge` raises and makes no changes when a later merge touched the
  same survivor.
- Case 1/2 merges are logged correctly: case 1's `moved_identity_ids` holds
  both identities, case 2's holds only the one that joined.
- Undoing a case 2 merge detaches only the identity that joined, leaving the
  pre-existing identity on the original person untouched.
- Full suite run afterward to confirm no regression in
  `test_resolution_rules.py` / `test_resolution_run.py`, both of which call
  `apply_merge` indirectly.
