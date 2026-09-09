## ADDED Requirements

### Requirement: Every confirmed merge is logged before mutation
`apply_merge` SHALL write one `merge_log` row before making any change to
`identity` or `person` rows. The row SHALL capture: the two identities that
triggered the merge, the survivor person id, the absorbed person id (null
when no second cluster existed), the survivor's `primary_name` and
`preferred_name` as they were before this merge, and the complete set of
identity ids whose `person_id` is about to change to the survivor as a
result of this call (`moved_identity_ids` — populated for every case, not
only when a second cluster is absorbed).

#### Scenario: Logging a first-time merge (no prior person on either side)
- **WHEN** `apply_merge` is called with two identities that both have no
  `person_id`
- **THEN** a `merge_log` row is written recording the new survivor person id,
  a null absorbed person id, `moved_identity_ids` containing both identity
  ids, and the (empty-string) name that existed before naming was computed

#### Scenario: Logging a merge where one side already has a person
- **WHEN** `apply_merge` is called with one identity that already has a
  `person_id` and one that has none
- **THEN** a `merge_log` row is written recording the existing person as
  survivor, a null absorbed person id, and `moved_identity_ids` containing
  only the identity that had no prior person

#### Scenario: Logging a cluster-union merge
- **WHEN** `apply_merge` is called with two identities that already belong to
  two different, non-null persons
- **THEN** a `merge_log` row is written recording the survivor person id, the
  absorbed person id, the survivor's prior `primary_name`/`preferred_name`,
  and `moved_identity_ids` containing every identity id that had `person_id`
  equal to the absorbed person id immediately before the merge

### Requirement: A logged merge can be undone
The system SHALL provide `undo_merge(cur, merge_log_id)` that reverses the
mutations of the referenced merge: it moves every identity id recorded in
`moved_identity_ids` to the absorbed person id (or, when there was no
absorbed person, detaches them back to no person at all), clears the
absorbed person's `merged_into` pointer when one exists, restores the
survivor's `primary_name` and `preferred_name` to the recorded prior values,
and stamps the log row's `reversed_at`.

#### Scenario: Undoing a cluster-union merge
- **WHEN** `undo_merge` is called with the id of a `merge_log` row for a
  cluster-union merge, and no later merge has touched the same survivor
- **THEN** the identities in `moved_identity_ids` are moved back to the
  absorbed person, the absorbed person's `merged_into` is cleared, the
  survivor's name fields are restored, and the log row's `reversed_at` is set

#### Scenario: Undoing a merge where one side had no prior person
- **WHEN** `undo_merge` is called for a merge that had a null
  `absorbed_person_id`
- **THEN** every identity id in `moved_identity_ids` is detached back to a
  null `person_id`, leaving any identity that already belonged to the
  survivor before the merge untouched

### Requirement: Undo is refused when a later merge touched the same survivor
`undo_merge` SHALL check for any other `merge_log` row with the same
`survivor_person_id` and a `merged_at` later than the merge being undone. If
one exists, `undo_merge` SHALL raise an error and make no changes, instead of
partially or silently reversing the merge.

#### Scenario: Later merge blocks an earlier undo
- **WHEN** `undo_merge` is called for merge X, and a merge Y with a later
  `merged_at` also has `survivor_person_id` equal to X's survivor
- **THEN** `undo_merge` raises an error, writes no changes, and does not set
  `reversed_at` on X's log row
