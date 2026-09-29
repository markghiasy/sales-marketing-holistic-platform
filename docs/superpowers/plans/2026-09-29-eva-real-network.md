# Eva Real Network Implementation Plan

> SUPERSEDED 2026-09-30: the approved [real Network trial design](../specs/2026-09-30-real-network-trial-design.md) uses a PostgreSQL derived schema, first validated on Eva's data, then shipped through the deployment skill for Mark's existing Mac installation. Execute the [replacement plan](2026-09-30-real-network-trial.md), not the SQLite tasks below. This document remains a historical planning record.

> 2026-09-29 evaluation update: read the [storage/framework evaluation](../../research/reports/2026-09-29-graphiti-storage-evaluation.md) before implementation. It recommends a relational knowledge layer first, with indexed PostgreSQL as the measured candidate, and defers Graphiti/Neo4j production adoption. This older plan specifies SQLite; SQLite was not benchmarked. Reconcile the derived-store choice and Task 2 with the design before executing this plan. No production implementation or database migration has been performed by the evaluation.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing local Inbox to a durable real-data network, with continuous incremental refresh, inspectable evidence and bounded strategy queries.

**Architecture:** Keep the source Postgres read-only for the network consumer. A single background worker reconciles source records into a local SQLite store, updating graph dependencies and lexical indexes atomically. Existing network UI uses a store/service boundary; source collection, deterministic projection and optional model extraction have independent health and freshness.

**Tech Stack:** Existing Python/Flask/Pydantic/psycopg, Python sqlite3/FTS5 after capability verification, existing browser/SSE and Anthropic integration. No new remote provider, broker or graph database.

**Spec:** `docs/superpowers/specs/2026-09-29-eva-real-network-design.md`, including the continuously changing Inbox section added after Eva's approval of the integration direction.

**Status:** Written and self-reviewed; not implemented. Execution recommendation: native implementation in this session, preserving the current worktree and production processes. A separate candidate instance precedes production cutover.

## Global Constraints

- SourceRepository 使用显式只读连接、超时和复用连接/受限连接池；查询字段与表明确列出，不读取 message.raw。
- 源库断连时显示最后成功版本和时间，不清空数据或退回 fictional fixtures。
- 模型生成的关系/画像一律 pending，审核状态持久化。
- 首次接入不自动全库抽取。
- 真实正文、索引、截图和密钥不进 git 或研究产物。
- 保留既有身份解析、消息导入、Inbox 隐藏/合并行为。
- Preserve existing user changes, including network.css and repo/.gitignore. Do not stage unrelated files.
- Existing production: 5001; do not take over 5000 or synthetic 5055/5056. Bind candidate only to loopback on a verified free port.
- No automatic source migration, external resync, credential replacement, cloud deployment, or production process restart during development.
- Initial defaults: debounce 2s, maximum debounce 10s, source batch 500 messages, incremental poll 60s with 24h lookback, metadata reconciliation 300s, complete reconciliation 900s. All configurable and covered by fake-clock tests.
- Performance goals are measurements to validate, not completion claims: normal new-message graph/search lag under 30s with notifications; fallback poll starts within 60s; correction/deletion bounded by the next successful reconciliation, not by an invented instant guarantee.

## Review Focus

1. A transaction begun before a saved cursor but committed after it must eventually appear: full reconciliation test in task 4.
2. A truncated reconciliation must never delete unseen records: manifest completeness/transaction test in task 2.
3. A confirmed capability whose supporting source changed or disappeared must not remain actionable: dependency invalidation test in tasks 3 and 6.
4. An answer generated while its subject was merged/reversed/hidden must not expose obsolete context: publication validation test in task 6.
5. A large ongoing import must neither starve UI reads nor move an Outlook cursor beyond uncommitted data: sustained-flow test in task 4 and commit-failure test in task 8.

## Deliverable sequence

Tasks 1–4 produce a recoverable background mirror and working incremental graph/search substrate. Tasks 5–7 expose it through the real UI and bounded agent. Task 8 closes an upstream cursor hazard. Task 9 validates a candidate and prepares a concrete production cutover. Dense retrieval/RRF/reranker and source outbox/CDC are later measured upgrades, outside this first implementation.

### Task 1: Read-only source contract and verified source binding

**Files:** Create `adapters/network/source.py`, `tests/test_network_source.py`, `scripts/network_audit.py`; inspect existing `db/migrations/0001_init.sql`, `0004_linkedin_connections.sql`, `0005_identity_resolution.sql` and `repo/runbook.md`.

**Interfaces:** Define immutable `SourceRecord(kind: str, id: str, fingerprint: str, payload: dict)` and `SourceBatch(records: tuple[SourceRecord, ...], manifests: dict[str, frozenset[str]], complete_kinds: frozenset[str], cursor: tuple[str, str] | None, observed_at: str, source_fingerprint: str)`. `SourceRepository.snapshot() -> SourceBatch`; `incremental(cursor, lookback_seconds: int, limit: int) -> SourceBatch`; `metadata() -> SourceBatch`; `reconcile() -> SourceBatch`; `validate(records: tuple[SourceRecord, ...]) -> bool`.

- [ ] Write `test_snapshot_excludes_raw_and_credentials`, `test_read_only_session`, `test_incremental_uses_ingested_time_and_id`, `test_old_schema_without_brief_status_is_supported`, `test_missing_required_table_is_explicit`, `test_source_identity_mismatch_stops_refresh`. Assert exact selected fields, immutable source IDs and no write SQL; fixtures include old messages newly ingested and equal timestamps across page boundaries.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_network_source.py -q` using the shared repo venv until the new contract fails for the expected missing implementation.
- [ ] Implement explicit field queries, read-only repeatable-read snapshots for full manifests, timeouts, stable canonical field hashing and source fingerprint. Complete manifests require successful exhaustion of all pages in that snapshot. Do not rely on ai_brief_status or infer a missing table means empty data.
- [ ] Add audit CLI with only aggregate counts/schema capabilities/source fingerprint in output. Verify the actual 5001 launch configuration and data source without printing DSNs; record mismatch as blocking cutover. Do not query or expose unrelated processes' credentials.
- [ ] Run tests with isolated Postgres; run a read-only real audit only after configuration binding is known. Commit only these task files.

### Task 2: Durable store, atomic refresh and rebuildable lexical index

**Files:** Create `adapters/network/store.py`, `adapters/network/index.py`, `tests/test_network_store.py`, `tests/test_network_index.py`; modify `.gitignore` only to exclude the dedicated `.network-data/` directory.

**Interfaces:** `PersistentNetworkStore(path: Path, source_fingerprint: str)`; `apply(batch: SourceBatch) -> int` returns committed data version; `capture() -> tuple[dict, int]`; `status() -> dict`; `wait_for_version(after: int, timeout: float) -> int`; `close()`. `LexicalIndex.search(text: str, limit: int, entity_ids: tuple[str, ...] = ()) -> list[dict]` returns source IDs, scores and snippets from the committed version. `record_failure(stage: str, code: str, at: str)` records sanitized health, never exception strings containing a DSN.

- [ ] Write and fail tests for duplicate batch idempotency, source binding mismatch, crash rollback, WAL readers seeing one version, reopening preserved progress, FTS5 capability failure and interrupted reconciliation not tombstoning absent pages.
- [ ] Implement SQLite tables for source records, dependencies, entities/edges, durable dirty work, review events, checkpoints, health and versions. Checkpoint advances in the same local transaction as indexed records. No-change refresh updates health timestamps without incrementing data version.
- [ ] Include message participants in content fingerprints. Complete manifests allow removal detection; incremental batches never imply deletion. Use parameterized FTS queries rather than passing raw user FTS syntax. Verify Chinese/name substring fallback separately; do not advertise full multilingual semantic search.
- [ ] Persist event/review data separately from replaceable index tables. Implement consistent SQLite backup and rebuild that preserve reviews; test restore and index regeneration with fictional data.
- [ ] Pass `tests/test_network_store.py tests/test_network_index.py`; commit explicit files.

### Task 3: Evidence-preserving real graph projection

**Files:** Create `adapters/network/real_projection.py`, `tests/test_network_real_projection.py`; modify `adapters/network/model.py`, `profiles.py`, `projection.py`, `scopes.py` only at compatibility seams.

**Interfaces:** `project_records(records: tuple[SourceRecord, ...], reviews: tuple[dict, ...], observed_at: str) -> dict` returns the existing graph-data shape with explicit `data_source='real'`, dynamic owner identity, provenance and unknown-time markers. `affected_entities(before: tuple[SourceRecord, ...], after: tuple[SourceRecord, ...]) -> set[str]` drives dependency invalidation in store.apply.

- [ ] Test aliases/self identities, unresolved identity contacts, same-name different people, self-sent CC, group messages, duplicated participants, late-arriving old messages, merge then reverse, deleted source support, hidden contacts and unknown employment dates. Assert no pairwise group clique, no synthetic records and no invented explicit/project relationship.
- [ ] Project direct interaction only with supported participant/direction semantics; preserve stable source identity mappings when canonical person changes. Pull organization associations from structured provenance. Treat conflicting accumulated works_at facts versus latest LinkedIn connection snapshot as conflict/unknown time, not simultaneous current jobs.
- [ ] Preserve independent evidence for edges: deleting one source retracts only its contribution, keeping a relationship supported by other valid sources. Reviews remain auditable but cannot keep an unsupported assertion active. Test multiple supporting sources explicitly.
- [ ] Derive recency from the query clock; historical filters remain fixed. Real defaults use current UTC and mapped self node; synthetic tests retain explicit fixture dates.
- [ ] Pass new tests and existing projection/scopes/profile suites; commit explicit changes.

### Task 3A: Explicit graph change policy and auditable proposals

**Status:** Proposed addition following Eva's clarification that graph mutation strategy is the missing product decision. Do not treat the new policy as already approved merely because the original ingestion architecture was approved.

**Files:** Create `adapters/network/changes.py`, `tests/test_network_changes.py`; modify `store.py`, `profiles.py`, `real_projection.py` and review service integration.

**Interfaces:** `ChangeProposal(id: str, operation: Literal['add', 'support', 'refine', 'end', 'supersede', 'conflict', 'retract'], subject_id: str | None, claim_ids: tuple[str, ...], source_ids: tuple[str, ...], expected_fingerprints: dict[str, str], payload: dict, status: Literal['pending', 'confirmed', 'rejected', 'unresolved'])`; `classify_change(candidate: dict, existing: tuple[dict, ...]) -> ChangeProposal | None`; `apply_review(proposal_ids: tuple[str, ...], decision: Literal['confirmed', 'rejected'], expected_version: int) -> int`. Source evidence removal is an authoritative invalidation operation separate from model-authored proposals.

- [ ] Fail tests for demand versus capability, quoted third-party claims versus speaker, ambiguous same-name subject, conditional future collaboration, past versus current project membership and compatible simultaneous jobs. Model extraction never directly creates confirmed semantic claims.
- [ ] Test exact source replay is no-op, same proposition aggregates valid independent support without duplicate tags, semantic equivalence proposed by a model requires review, and unresolved subject blocks publishing a person-specific relation.
- [ ] Test latest-by-message-time does not automatically win a conflict; a newly suspected contradiction adds a warning/proposal without erasing approved evidence. Definite source deletion retracts only that source, with alternate valid supports retained.
- [ ] Test role handover publishes end/add as one reviewed transaction only after successor identity is resolved; preserve historical roles and reject stale proposal fingerprints. Unknown effective dates remain unknown.
- [ ] Store proposals, support links and review events durably; apply graph/tag/search eligibility through the same projection policy. Track observed time separately from effective time. Rebuild reproduces reviewed state without rerunning model calls.
- [ ] Pass changes/projection/profile suites with fictional sources; commit explicit files after the added policy is approved.

### Task 4: Single-worker incremental refresh and reconciliation

**Files:** Create `adapters/network/sync.py`, `scripts/network_sync.py`, `tests/test_network_sync.py`; modify source/store contracts only as defined above.

**Interfaces:** `NetworkSync(source: SourceRepository, store: PersistentNetworkStore, clock: Callable[[], datetime], config: SyncConfig)`; `tick() -> None`, `wake(message_id: str) -> None`, `stop() -> None`. `SyncConfig` contains the exact defaults in Global Constraints. CLI `python -m scripts.network_sync --config <local-config-path>` acquires a single-writer lease and supports graceful shutdown.

- [ ] Write fake-clock tests: notification burst coalesces, continuous arrivals flush by 10s, 500-row batches preserve fairness, 60s poll catches missed notification, 300s metadata detects merge/reverse, 900s full scan catches old-transaction commit and deletion, restart after partial batch replays safely, same-time IDs do not skip, source outage never switches to fixtures.
- [ ] Implement committed LISTEN before initial snapshot, dedicated short-lived/read-only source transactions, reconnect backoff capped at 60s and persistent local dirty work. LISTEN failure leaves polling usable; it does not block the app.
- [ ] Queue source invalidations idempotently; re-read authoritative records rather than trusting event payload contents. Persist successful checkpoints only after local application. Reconcile missing source notifications with the configured complete scan.
- [ ] Test two worker starts: second cannot process concurrently for the same data directory; expired leases recover after crash. UI workers do not own sync lifetimes. Record last_applied_at, last_reconciled_at and separate source/worker failures.
- [ ] Run new sync/store/source suites; commit explicit files. Do not register a production scheduled task yet.

### Task 5: Shared service routes and real network candidate

**Files:** Create `adapters/network/service.py`, `scripts/network_local.py`, `tests/test_network_real_app.py`; modify `scripts/network_demo.py`, `scripts/onboarding/app.py`, `scripts/onboarding/templates/inbox.html`, and discovered network templates/static JS files. Locate exact existing frontend owners with `rg --files scripts/onboarding` before editing; preserve user CSS changes.

**Interfaces:** `NetworkService(store, source, provider)`; `register_network_routes(app: Flask, service: NetworkService) -> None`. Existing public graph/search/evidence/profile/events endpoints retain URL/JSON compatibility. `NETWORK_ENABLED` enables routes independently of `NETWORK_DATA_SOURCE=real|synthetic`; missing real config is an explicit error, never fixture fallback.

- [ ] Test real app cannot serve simulate/reset, real route errors do not load fixtures, correct loopback/Host/Origin rules, existing Inbox hide/merge/read endpoints remain unchanged, and source schema lacking ai_brief_status does not break the candidate network routes.
- [ ] Extract shared route behavior while keeping demo-only Inbox stubs and scenario mutations in the demo factory. Adapt capture/snapshot/search against the persistent store/index; do not copy all messages or rebuild a token index for each request. Use a bounded relevant context query for agent calls.
- [ ] Add status endpoint and version events; event payload carries committed version, not raw message IDs/text. Browser reconnect explicitly fetches the current version to recover missed events.
- [ ] Show per-channel last successful collection where known, graph updated/reconciled timestamps and pending extraction. Patch changed nodes/edges while preserving layout, selection, filters and viewport. Tests assert history mode is stable and current mode refreshes without page reload.
- [ ] Run new app tests, existing demo integration and relevant browser suites. Candidate initially binds a verified free loopback port. Commit explicit task files.

### Task 5A: Close the Inbox brief and tag refresh loop

**Files:** Create `adapters/network/brief_jobs.py`, `tests/test_network_brief_jobs.py`; modify `adapters/ai_brief.py`, `adapters/network/source.py`, `store.py`, `service.py`, all three channel `sync.py` entrypoints and existing Inbox frontend refresh handlers. Extend channel sync tests. This task implements the spec's additional Inbox summary/context/tag section; runtime compatibility must be verified before cutover.

**Interfaces:** `BriefJobRunner(store, source, provider).run_one() -> bool`; store `enqueue_brief(person_key: str, input_fingerprint: str) -> None`, `get_brief(person_key: str) -> dict | None`, `publish_brief(person_key: str, input_fingerprint: str, result: dict) -> bool`. Publish returns false if current input/dependencies no longer match. `AI_BRIEF_REFRESH_MODE` accepts only inline or queued, defaults inline. Candidate imports existing ai_brief cache but does not automatically run paid replacement jobs.

- [ ] Fail tests for outbound-only change refreshing the non-self recipient, duplicate message replay doing no paid work, aliases/participants not duplicating message text, metadata-only changes invalidating brief, merge/reverse invalidating subject, and stale generation losing to a newer version.
- [ ] Separate prompt/input/generation logic from source-DB cache writes so queued mode writes only the local derived store. Persist current summary/context/topic/urgency with evidence IDs and input version; preserve legacy graph as unverified cache, never confirmed graph edges. Current context output requires a versioned schema extension for per-item citations; test unsupported/misattributed citations rejected.
- [ ] Coalesce by canonical contact plus content/model/prompt fingerprint; successful generation atomically publishes all brief fields and a brief_updated event. Claims from the optional profile extractor remain separate pending assertions. Do not create three paid calls for the three visible brief fields.
- [ ] Keep inline behavior compatible by default. In queued mode, channel ingestion skips inline model generation; the durable network worker discovers committed changed messages and metadata using its existing recovery mechanism. Candidate automatic generation remains off until coordinated cutover so old and new pipelines cannot double-spend.
- [ ] Test startup recovery, failure/backoff preserving last successful brief, explicit queued/running/stale/failed/ready status, and compatibility fallback when ai_brief_status is absent. Missing source status must be reported as unknown, not assumed healthy.
- [ ] Browser test: receive a message event followed by brief_updated; both list preview and an already open contact's context update without closing the panel or moving scroll. A slow old event cannot revert newer content. Multi-tags continue to derive from verified evidence rather than the topic string.
- [ ] Implement real contact tags as the same-version graph/profile projection, never a separate LLM-generated label list. Group supports by canonical person/facet/relation/value key; extend the tag response with support IDs, provenance, validity and review/dispute status. Do not reuse the demo's single-assertion ID as the stable identity of a multi-source label.
- [ ] Test a cybersecurity-topic-only message creates no expertise tag; a pending project-role assertion creates no confirmed tag; confirming the assertion makes graph/search/tag eligibility agree at the same version. A detected role-ending conflict is marked disputed and excluded from unqualified current recommendations until resolved, without erasing history.
- [ ] Test duplicate evidence produces one label with multiple supports; removing one support preserves labels with other valid supports; removing all supports invalidates graph/search/tag eligibility together. Rename preserves tag identity; no-op ingest preserves the tag set/version.
- [ ] Add browser tests for stable three-tag preview plus +N, fixed initial category ordering, newly eligible tags entering overflow without replacing still-valid visible tags, and effective invalidation removing stale tags despite pinning. Persist pin preference separately from facts; allow pin/unpin in full tag detail. Old frontend events must not undo newer tag state.
- [ ] Run new brief tests, channel sync/ai_brief tests and Inbox browser tests with fake model clients; commit explicit files. Add coordinated inline/queued switch and rollback to task 9's cutover package.

### Task 6: Persistent profile review and version-aware strategy answers

**Files:** Modify `adapters/network/profiles.py`, `agent.py`, `retrieval.py`, `store.py`, `service.py`; create `tests/test_network_real_agent.py`, `tests/test_network_real_reviews.py`.

**Interfaces:** Store exposes existing-compatible `review_profile(assertion_id, status, subject_id, version) -> dict` and `add_profile_proposals(rows, version) -> dict`. Add `validate_dependencies(dependencies: tuple[SourceRecord, ...]) -> bool` at service boundary, delegating authoritative reads to source.validate. Agent receives indexed, bounded candidate/evidence data plus a version and dependency manifest.

- [ ] Test review persistence across restart/rebuild, extraction dedup by source/content/model/prompt version, rejected same-version claims not resurrected, corrected-source claims lose prior confirmation, source deletion/hidden/identity reversal during a model call suppresses obsolete publication, and unrelated arrivals do not discard valid answers.
- [ ] Query lexical/structured candidates before constructing the planner catalog; retain candidates per requirement within existing context budgets. Replace request-time full catalog/token rebuild. No new dense provider or hosted embedding call.
- [ ] Keep deterministic updates independent of paid calls. Extraction requires explicit enablement and limits; persist pending/retry status and dedup keys. Retries must not blindly repeat a successful paid call whose validated result was already stored.
- [ ] Validate evidence before sending and before publishing. Surface updated-context retry when relevant dependencies changed; do not automatically burn another call indefinitely. Keep generated-at/data-version metadata on previous answers and mark known-invalid citations.
- [ ] Replace the demo global one-request lock with bounded admission (initial 2 active, 4 waiting, 120s overall deadline); test queue-full response, cancellation and stage timeout without provider calls. Preserve per-session budget enforcement.
- [ ] Pass agent/retrieval/profile suites with fake providers and network disabled. Real smoke later uses at most two explicitly budgeted questions. Commit task files.

### Task 7: Timing, recoverability and capacity report

**Files:** Create `scripts/benchmark_network_local.py`, `tests/test_network_observability.py`, `docs/demos/real-network-acceptance.md`; modify sync/service/index timing instrumentation.

**Interfaces:** Every refresh/search/agent operation emits a sanitized structured timing record: stage, duration_ms, counts, version, outcome and correlation ID; no names, queries, snippets or credentials.

- [ ] Test status distinguishes collection success from downstream failure, idle channels from disconnected ones, and unchanged successful sync from a frozen graph. No last-message-time-only health signal.
- [ ] Measure source scan, queue lag, local commit, candidate recall, context assembly, model preflight/call and rendering separately. Benchmark actual local scale plus fictional 10x/100x evidence sets and concurrency 1/5/20; report resource use and real denominators, not extrapolated promises.
- [ ] Exercise restart, source outage, index rebuild, review backup/restore and sustained import during queries. Verify graph/search results reference the same committed version.
- [ ] Record which timing goals passed and where polling/reconciliation impose known staleness. If 900s scans cannot finish comfortably, hold scale rollout and propose outbox/index changes based on measurements.
- [ ] Run observability/sync tests; commit code and aggregate-only report.

### Task 8: Close the upstream Outlook checkpoint failure window

**Files:** Modify `adapters/outlook/sync.py`; extend `tests/test_outlook_sync.py`.

**Interfaces:** Keep `run()` public contract. Accumulate returned folder delta links in memory; persist them only after the source DB commit succeeds. Write each file atomically. If a later file write fails, the next run may replay already committed messages, which must remain idempotent.

- [ ] Write `test_commit_failure_preserves_all_folder_delta_links`, `test_fetch_failure_does_not_advance_links`, `test_success_commits_before_saving_links`, `test_post_commit_checkpoint_failure_can_replay_without_duplicates` with fake provider/file paths and isolated DB.
- [ ] Verify failing tests expose the existing pre-commit write ordering, then implement the smallest change. This task must not modify source tokens or fetch external messages during tests.
- [ ] Run Outlook sync/store-writer and relevant ingestion suites. Record the observed failure window as corrected by tests, not proof of previous production data loss.
- [ ] Commit explicit task files. Installing this change into the active checkout belongs to cutover, not to this test step.

### Task 9: Candidate verification and concrete production cutover package

**Files:** Update `docs/demos/real-network-acceptance.md`, create `docs/runbooks/eva-local-network.md`; modify deployment wrappers/config examples only after confirming actual running service commands.

- [ ] Verify running 5001 source binding, branch/schema compatibility and all current production user modifications. Inventory only relevant process metadata; do not dump process environments.
- [ ] Start candidate with a separate gitignored data directory, verified free loopback port and hidden background process. Initial source import is read-only; report exact per-channel/identity/organization coverage against the source snapshot. Do not call the older 7,338 count immutable.
- [ ] Inspect real UI locally: no synthetic labels/records, correct self identity, source evidence, empty/unknown unsupported project layers, working refresh and preserved Inbox behavior. Avoid writing real screenshots into repo.
- [ ] Validate limited real question behavior with an explicit maximum of two API calls to the agent endpoint (provider subcalls still count toward token/request budgets). Record only aggregate timing and citation-validation outcomes.
- [ ] Run the affected test suites and required repository CI checks on the candidate. Existing 505 passing synthetic tests from an earlier commit are not evidence for this version.
- [ ] Write exact service stop/start commands, explicit file/config changes, backup locations, schema compatibility findings and rollback commands based on the observed launcher. Do not replace the entire onboarding app if its queries depend on absent production migrations; port only the compatible route/config changes or present a separately reviewed migration plan.
- [ ] Present the concrete candidate URL, verification report and cutover diff. Apply production cutover only under the already-authorized scope or a necessary final approval; never stop the current service to discover whether the candidate works. Recheck Inbox and source tasks afterwards and record rollback readiness.

## Self-review result

The plan covers persistent real data, four evidence scopes, dynamic source changes, aliases/merges, source-backed reviews, search bounds, agent freshness, real UI integration, source compatibility and rollback. All five review-focus risks have explicit owning tests. Deferred items are dense/hybrid retrieval, outbox/CDC and unattended large-scale LLM extraction; the initial release must label these as absent. The remaining approval is review of this implementation plan and execution method, not a new decision about deployment location.
