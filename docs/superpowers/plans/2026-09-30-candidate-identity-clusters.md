# Candidate identity aggregation implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, with one fresh whole-branch review at the end.

**Goal:** Ship Mark's deterministic-merge / heuristic-suggestion policy, bounded provisional statistics, and filed-mail coverage.

**Architecture:** A read-only candidate component service owns membership and safety checks; the reply signal and contact panel consume it. Database revision tracking invalidates candidate-dependent briefs. Resolution run provenance and Outlook discovery remain separate modules.

**Tech Stack:** Python, PostgreSQL, Flask, existing JavaScript inbox, Graph REST v1.0.

**Spec:** `docs/superpowers/specs/2026-09-30-candidate-identity-clusters.md`

## Global constraints

- Maximum 8 identities; minimum 50% unique undirected edge density.
- Only exact_email may merge automatically; human confirmation remains available.
- Default Outlook folder scope unchanged; 0013 preserves decided history.
- No production DB writes or live paid bulk backfill. Push is already authorized.

## Review focus

- Duplicate/reverse candidate edges cannot inflate density; the 9th identity cannot be silently trimmed to pass.
- Confirmed multi-identity contacts, rejection through an alternate path, and self/hidden identities must not leak into provisional attribution.
- Candidate removal and new messages on the other fragment must not leave a stale brief asserted as current.
- Localized folder names, duplicate Inbox display names, empty parents with populated children, and deep nesting must retain correct cursor and exclusion behaviour.
- A later folder failure must not advance checkpoints past uncommitted mail; provider/schema failures must remain observable.

### Task 1: Merge policy and signature retirement

**Files:** rules.py, merge.py, migration 0013, tests/test_resolution_rules.py, tests/test_resolution_quality_fixes.py.
**Interfaces:** Existing rule functions retain integer results; signature result means detected only. apply_merge rejects non-exact automatic decisions before writing.

- [x] Write tests: contact bridge leaves both person_id null and merge_log empty; direct automatic heuristic apply_merge raises; signature detection returns a count but inserts nothing; migration retires pending rows only, idempotently.
- [x] Run targeted tests and observe RED.
- [x] Implement policy and supplied retirement migration.
- [x] Run targeted tests; expected PASS. Commit.

### Task 2: Bounded component, statistics, UI and brief freshness

**Files:** new adapters/resolution/clusters.py, reply_signal.py, ai_brief.py, inbox_query.py, contact_editor.py, onboarding app/template, new migration and cluster tests.
**Interfaces:** candidate_cluster(cur, contact_key) returns own/member identity IDs, direct suggestions, allowed flag, density and reason. reply_signal retains its four existing fields and adds aggregation metadata. Contact API exposes suggestions and provisional counts separately from known handles.

- [x] Test pair aggregation with duplicate message participants; 8-node/50% boundary, 9 nodes, sparse chain, reverse duplicate edges, rejected alternate path, retired/self/hidden exclusions and confirmed identity groups.
- [x] Test API suggestion evidence and conservative fallback; brief prompt preserves uncertainty; invalidation on candidate edit/removal and partner-message arrival.
- [x] Observe RED; implement read-only component service, statistics and UI, plus cache freshness protection.
- [x] Run component, brief, inbox, contact and route tests; expected PASS. Commit.

### Task 3: Outlook discovery and reliable checkpoints

**Files:** outlook/client.py, sync.py, tests/test_outlook_client.py, tests/test_outlook_sync.py, example configuration and runbook.
**Interfaces:** discover_folders() -> list[tuple[str,str,int]]; _folders_to_sync() -> list[tuple[str,str]]; _delta_link_path(folder_key) -> Path.

- [x] Test default opt-in, localized built-ins, duplicate names, paged/deep traversal, excluded descendants, empty parents, retry use, safe filename hash, draft exclusion and checkpoint order on failure.
- [x] Observe RED; adapt Mark's patch with these safeguards.
- [x] Run Outlook tests; expected PASS. Commit.

### Task 4: Run attribution and release

**Files:** resolution/run.py, new provenance migration, review API/template, tests/test_resolution_run.py, delivery notes.
**Interfaces:** rule-run context attaches run_id, rule_version, code_revision to newly inserted candidates; run report distinguishes detected observations from candidates written.

- [x] Test attribution and isolated rule failure; retain pre-upgrade candidates with unknown provenance.
- [x] Observe RED; implement, verify and commit.
- [x] Full suite and Ruff; fresh whole-branch reviewer; fix material issues with reproducing tests.
- [ ] Save Mark reply and upgrade notes; push branch and create reviewable PR. Verify remote commit and CI.
