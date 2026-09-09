## Why

Identity resolution's `apply_merge` (adapters/resolution/merge.py) has three merge
scenarios. Scenario 3 — unioning two person clusters that were each already
independently resolved — currently overwrites `identity.person_id` and the
survivor's `person.primary_name`/`preferred_name` with no record of the
pre-merge state, so a wrong merge cannot be undone and there is no audit trail
of what merged into what or why. Eva has committed to Mark that this will be
fixed and that merges will be logged.

## What Changes

- Add a `merge_log` table that records, for every `apply_merge` call, enough
  pre-merge state to invert it: which identities moved, the survivor's prior
  name, and merge provenance (timestamp, the two identities that triggered
  the merge, survivor/absorbed person ids).
- `apply_merge` writes one `merge_log` row before mutating anything.
- Add `undo_merge(cur, merge_log_id)` that reverses a merge using its log row:
  moves the recorded identities back to the absorbed person, clears its
  `merged_into` pointer, restores the survivor's prior name, and stamps the
  log row as reversed.
- `undo_merge` refuses to run (clear error, no mutation) if a later
  `merge_log` row touches the same survivor person — a later merge may have
  built on identities this undo would pull back out, so the later merge must
  be dealt with first.

## Capabilities

### New Capabilities
- `identity-merge-audit`: recording and reversing confirmed identity merges

### Modified Capabilities
(none — no existing spec file covers merge behavior today)

## Impact

- `adapters/resolution/merge.py`: `apply_merge` gains a log-write step; new
  `undo_merge` function.
- `db/migrations/`: new migration adding `merge_log` table.
- No UI/API surface for triggering undo yet — this change covers the data
  model and the two functions only. Whether undo gets exposed through
  `scripts/onboarding/app.py` or stays a maintenance-only entry point is a
  separate follow-up decision.
