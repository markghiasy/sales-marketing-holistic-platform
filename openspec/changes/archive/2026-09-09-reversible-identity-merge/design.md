## Context

`apply_merge` (adapters/resolution/merge.py) is the single place that creates
person rows and sets `identity.person_id`. It handles three cases based on
whether `identity_a`/`identity_b` already belong to persons:

1. Neither identity has a person yet → new person created, both attached.
2. One identity already has a person → the other joins it.
3. Both identities already have *different* persons → every identity under
   the loser's person is moved to the winner's person, and the loser person
   is soft-merged via `person.merged_into` (schema comment: "reversible,
   never delete rows").

Case 3 is the one that isn't actually reversible today, because reversing it
requires knowing exactly which identity rows moved and what the winner's name
was before `select_names` recomputed it — neither is recorded anywhere.
`person.merged_into` records *that* a merge happened and *where it went*, not
*what* moved or *what was overwritten*.

## Goals / Non-Goals

**Goals:**
- Every `apply_merge` call leaves a durable, auditable record of what it did.
- Case 3 merges can be exactly inverted via `undo_merge`.
- Undoing a merge is refused (not silently wrong) when a later merge has
  already built on the same survivor cluster.

**Non-Goals:**
- No UI or API for triggering undo — `undo_merge` is a function other code
  (or a maintenance script) calls directly. Deciding how a human triggers
  this is a separate follow-up.
- No general-purpose "merge event sourcing" — this only logs enough to
  invert the single most recent state change from one `apply_merge` call.
- Cases 1 and 2 are trivially reversible already (a single identity moving
  to/from a freshly created or previously person-less row), but we still log
  them for audit consistency and so the "same survivor touched later" check
  in `undo_merge` has complete data to check against.

## Decisions

**One `merge_log` row per `apply_merge` call, written before any mutation.**
Alternative considered: derive the pre-merge state after the fact from
`person.merged_into` + timestamps. Rejected — `merged_into` doesn't capture
which specific identities moved, and later merges into the same survivor
make that undecidable after the fact. Writing the snapshot up front is the
only point at which the "before" state is known precisely.

**`moved_identity_ids` is populated for all three cases, not just case 3.**
An earlier draft tried to recover the case-1/2 identity from
`identity_a_id`/`identity_b_id` directly instead of logging it. That breaks
for case 2 specifically: the two columns are symmetric, so nothing
distinguishes "the side that already belonged to the survivor" from "the
side that joined" once other merges have touched the survivor since.
Recording the actual moved set — one id for case 2, two for case 1, the
whole absorbed cluster for case 3 — is the same mechanism every time.

**`prev_primary_name`/`prev_preferred_name` capture the survivor's name
before `select_names` recomputes it.** This is the only way to restore the
name on undo, since the recompute is destructive and not derivable from
current state once other merges have also touched the cluster.

**Undo refuses if a later `merge_log` row has the same `survivor_person_id`
and a later `merged_at`.** This was chosen over the two alternatives Eva
considered: (a) always allow the undo with no check, and (b) allow but leave
manual cleanup to a human. Rationale: a later merge may have absorbed more
identities into the same survivor, or relied on the cluster containing the
identities this undo would remove; silently reversing under those conditions
can produce a state where an identity that a later merge's logic depended on
disappears from the cluster with no warning. Refusing forces the operator to
undo the later merge first (or accept that this one can no longer be cleanly
reversed), which is a safer default than an automatic reversal that might be
wrong.

## Risks / Trade-offs

- **[Risk]** Refusing undo when a later merge touched the same survivor is
  conservative — it can block a legitimate undo even when the later merge is
  unrelated to the identities being pulled back out. → **Mitigation**: this
  is a data-integrity default, not a hard wall; an operator can still undo
  the later merge first, then the earlier one, in order. No case is
  permanently stuck.
- **[Risk]** `merge_log` grows unboundedly as merges accumulate. → No
  mitigation planned now — merge volume is expected to stay small
  (person-cluster consolidation, not a high-frequency event); revisit if
  volume changes.
- **[Trade-off]** Logging happens inside the same transaction as the merge
  mutations (same `cur`), so a partial failure can't leave a merge applied
  without a log row, or vice versa — this is deliberate and requires no
  extra work, since `apply_merge` already runs under one caller-managed
  transaction.

## Migration Plan

- New forward-only migration adding `merge_log` (no backfill — merges applied
  before this change have no recoverable pre-merge snapshot and simply
  aren't undoable, which matches today's reality).
- No rollback needed beyond a standard down-migration dropping the table;
  nothing else depends on `merge_log` existing.

## Open Questions

None outstanding — the chained-merge handling was the open design decision
and Eva resolved it (refuse undo when a later merge touched the same
survivor).
