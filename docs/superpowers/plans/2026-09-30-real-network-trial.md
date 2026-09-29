# Real Network Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the existing network demo interactions on Eva's real records, then deliver a reproducible upgrade skill for Mark's existing Mac installation.

**Architecture:** Read source PostgreSQL through enforced read-only connections; maintain a versioned derived `network` schema in the same database. A single recoverable worker feeds an independent loopback trial service, keeping graph, labels and indexed search consistent. Existing collectors and Inbox continue running.

**Tech Stack:** Python >=3.11, existing Flask/Pydantic/psycopg/Anthropic dependencies, PostgreSQL, existing Cytoscape UI; no new database service or embedding provider.

**Spec:** [Approved real-network trial design](../specs/2026-09-30-real-network-trial-design.md).

**Status:** 2026-09-30: design and native execution approved. Tasks 1–5 have implementation commits and passing targeted tests; Tasks 6–8 remain. Real DB access so far is a read-only audit; no real derived schema initialization, app cutover or live model probe yet. Supersedes the SQLite execution steps in [the older plan](2026-09-29-eva-real-network.md). Detailed verification and rulings are in this plan's execution ledger.

## Global Constraints

- Eva real-data validation → update deployment skill → Mark self-deploys. Friday 2026-10-02 is a trial target, not a verified release date.
- Source connections are read-only; all derived SQL qualifies the `network` schema. Explicit initialization only; never replay all historical source migrations or ignore duplicate-table errors.
- Preserve stable person/identity IDs, hidden-contact boundaries and source evidence. No name-based merging, group/CC acquaintance cliques, synthetic fallback or cached-summary promotion into facts.
- Initial configurable refresh intervals: 60 seconds incremental, 300 seconds metadata, 900 seconds full reconciliation. These are schedules, not end-to-end SLAs.
- Incremental cursor is `(ingested_at, id)`, with lookback and periodic reconciliation. Checkpoint, projection and search changes publish atomically.
- Real defaults use current UTC and the verified owner; synthetic tests supply fixture dates explicitly.
- Real trial has no simulated reply/reset endpoints. Model failure must leave basic graph and lexical search usable.
- No credentials, real messages or private research corpora in tracked files, diagnostic logs or artifacts. Do not read `message.raw`.
- Preserve existing services on 5000/5001/5055/5056, the user's existing CSS edit and unrelated working-tree files. Never stage all files.
- New algorithm experiments, full project management, automatic outreach and rewriting existing summary generation are outside this release.

## Review Focus

1. Old source schema lacking `ai_brief_status` must work; a missing required source table must fail clearly (Task 1).
2. A late-committing import behind the cursor must eventually appear; partial reconciliation must never delete unseen records (Tasks 1, 4).
3. Merge reversal, hiding or a correction while a model call runs must invalidate the affected answer, while an unrelated new message must not (Tasks 3, 6).
4. A person mentioning a project does not establish membership; rejecting then restarting must not revive the proposal (Task 5).
5. A source checkout can work while a clean install lacks templates/assets; test the exact shipped layout and distinguish Windows verification from Mac verification (Task 8).

## Files and responsibilities

| Files | Responsibility |
|---|---|
| New `adapters/network/source.py`, `scripts/network_audit.py` | Explicit source reads, schema/source binding, paged snapshots and sanitized audit |
| New `db/network/0001_network.sql`, `adapters/network/store.py`, `scripts/network_schema.py` | Versioned derived schema, atomic updates, dependency and review persistence |
| New `adapters/network/real_projection.py` | Source-backed canonical entities, relations and activity; reuse existing projection/scopes |
| New `adapters/network/worker.py`, `scripts/network_worker.py` | Single-writer schedules, replay, recovery and health |
| New `adapters/network/changes.py` | Validated entity/relation/profile proposals and review commands |
| New `adapters/network/index.py`, `service.py` | Bounded retrieval, consistent graph/evidence reads, lifecycle checks |
| Modify `adapters/network/model.py`, `profiles.py`, `agent.py`, `retrieval.py` | Narrow seams for clock/owner, extraction, retrieval injection and freshness validation |
| New `scripts/network_real.py`; modify `scripts/network_demo.py` | Shared route wiring with injected service; demo fixture default stays explicit |
| Modify `scripts/onboarding/templates/network.html`, existing `static/network/*.js` only where required | Real source/freshness, bounded results, extraction/review, no demo controls in real mode |
| Modify `tests/conftest.py`; new `tests/test_network_{source,store,real_projection,worker,changes,index,real_agent,real_app}.py` | Fictional PostgreSQL fixtures and behavioral acceptance tests |
| New `scripts/check_network_real.py`, `scripts/research/network_trial_benchmark.py`, release report; deployment skill/runbook | Reproducible trial, performance record and operator upgrade |

Paths above are relative to `network-demo-worktree`. Skill entry currently exists at sibling `repo/.agents/skills/deploy-comms-platform/SKILL.md`; reconcile it with tracked `.claude/skills/deploy-comms-platform/SKILL.md` before publishing. Never silently edit a different checkout's product code.

## Test environment and common types

Use the existing repo venv, from this worktree: `& '../repo/.venv/Scripts/python.exe' -m pytest <test paths> -q`. Reuse `tests/conftest.py`'s guarded `TEST_DATABASE_URL` (loopback host, disposable test database name, never application `.env`); extend it for source/derived schema separation and serialize tests that require the literal `network` schema. Never create/drop source tables outside that isolated database. Unit tests use injected repositories/providers; source/store acceptance must also run against actual isolated PostgreSQL. No real DSN in test output.

Task 1 defines frozen `SourceRecord(kind: str, id: str, fingerprint: str, payload: dict)`, `Cursor(ingested_at: datetime, id: str)`, and `SourceBatch(records: tuple[SourceRecord, ...], cursor: Cursor | None, manifests: dict[str, frozenset[str]], complete_kinds: frozenset[str], observed_at: datetime, binding: str)`. A manifest is authoritative only when its complete repeatable-read snapshot has finished.

Task 2 defines `Snapshot(version: int, data: dict, dependencies: dict[str, str])` and `NetworkStatus(version: int, last_success_at: datetime | None, source_checked_at: datetime | None, error_code: str | None)`. Task 3 defines `Projection(entities: tuple[dict, ...], assertions: tuple[dict, ...], evidence: tuple[dict, ...], dependencies: dict[str, tuple[str, ...]])`. Serialized payloads adapt to the existing demo response contract; no new unvalidated model-output dictionaries bypass existing Pydantic validators.

### Task 1: Source boundary and safe audit

**Files:** New `source.py`, `network_audit.py`, `test_network_source.py`; extend existing `tests/conftest.py` from the map. Inspect `db/migrations/0001_init.sql`, `0004_linkedin_connections.sql`, `0005_identity_resolution.sql` and later source migrations.

**Interfaces:** `SourceRepository.snapshot_pages(page_size: int) -> Iterator[SourceBatch]`; `incremental(cursor: Cursor | None, lookback_seconds: int, limit: int) -> SourceBatch`; `metadata() -> SourceBatch`; `validate(dependencies: dict[str, str]) -> bool`; `audit() -> dict`. `snapshot_pages` has one repeatable-read transaction; only its terminal batch contains completed manifests. Dependency keys include identity/person mapping and visibility, not only message body hashes.

- [ ] Write tests asserting old-schema compatibility, no `raw` selection, database-enforced read-only writes rejected, source binding mismatch rejected, equal-timestamp pagination, old sent-time/new ingest-time inclusion and interrupted snapshot lacking complete manifests.
- [ ] Run `test_network_source.py`; confirm failures identify absent source implementation, not a misconfigured test database.
- [ ] Implement the interfaces with parameterized explicit-field SQL, timeouts and stable fingerprints. A source with no resolvable self identity reports `owner_unresolved`; multiple aliases mapping to one canonical self are supported. Audit emits counts/capabilities and an opaque binding fingerprint, never DSN or message text.
- [ ] Run `test_network_source.py` against isolated PostgreSQL; confirm all assertions pass, including participant/canonical-mapping changes affecting fingerprints.
- [ ] Commit only Task 1 files with `feat: add read-only network source adapter`.

### Task 2: Versioned durable store

**Files:** New `db/network/0001_network.sql`, `store.py`, `scripts/network_schema.py`, `test_network_store.py`.

**Interfaces:** `PostgresNetworkStore.apply(batch: SourceBatch, projection: Projection) -> int`; `capture(entity_ids: tuple[str, ...], limit: int) -> Snapshot`; `status() -> NetworkStatus`; `wait_for_version(after: int, timeout: float) -> int`; `dependencies_current(dependencies: dict[str, str]) -> bool`. CLI `python -m scripts.network_schema --env-file PATH --check` is read-only; `--initialize` performs explicit version/binding-checked derived initialization.

- [ ] Write tests for binding/version mismatch, wrong schema privileges, idempotent replay, failure before commit, concurrent reader consistency, restart persistence and a derived connection attempting to write a source table. Assert source state is unchanged and committed version/checkpoint move together.
- [ ] Run `test_network_store.py` and capture expected missing-store failures.
- [ ] Implement source mirrors, normalized entities/assertions/evidence, support dependencies, append-only review events, checkpoints, health and indexes. Constrain derived business SQL to `network`; use database privilege separation where available, test the actual privilege boundary. Preserve reviews on projection/index rebuild. No-change batches update health without inventing a data revision.
- [ ] Run the store tests; additionally restore an isolated derived backup and rebuild projections without losing review history. Initialization must reject unknown schema versions rather than treating duplicate objects as success.
- [ ] Commit only Task 2 files with `feat: persist network versions and review history`.

### Task 3: Source-backed projection and consistent labels

**Files:** New `real_projection.py`, `test_network_real_projection.py`; narrow modifications to `model.py`, `profiles.py`, `projection.py`, `scopes.py`, `search.py`.

**Interfaces:** `project_records(records: tuple[SourceRecord, ...], reviews: tuple[dict, ...], observed_at: datetime) -> Projection`; `affected_entities(before: tuple[SourceRecord, ...], after: tuple[SourceRecord, ...]) -> set[str]`. Reuse existing graph/scopes/tag functions over eligible projected assertions. Projection runs on changed dependency neighborhoods; full rebuild is an explicit recovery operation, not each browser request.

- [ ] Write tests for same-name people, unresolved identities, self aliases, group/CC messages, merge/undo, hidden contacts, multiple independent supports and corrected/deleted supports. Assert shared employer does not imply acquaintance and cached briefs cannot establish graph facts.
- [ ] Run `test_network_real_projection.py` to see the expected missing-projection failures.
- [ ] Implement stable source IDs and four evidence-based scopes. Derive graph, search eligibility and labels from the same assertions/version. Current LinkedIn snapshots and accumulated employment facts can conflict; preserve provenance and unknown time instead of declaring all historical employers current. Keep unsupported projects empty and real clock/owner explicit.
- [ ] Run the new suite plus `test_network_projection.py`, `test_network_scopes.py`, `test_network_profiles.py`, `test_network_search.py`; assert a deleted support retracts only that support, while another valid support preserves the relation.
- [ ] Commit only Task 3 files with `feat: project real relationships with shared label evidence`.

### Task 4: Incremental worker and reconciliation

**Files:** New `worker.py`, `scripts/network_worker.py`, `test_network_worker.py`; integrate Task 1–3 interfaces.

**Interfaces:** `NetworkWorker.tick(now: datetime) -> NetworkStatus`; `run(stop: threading.Event) -> None`. Worker takes source/store and configurable intervals, page/batch limits and lookback. Hold a PostgreSQL advisory lock scoped to derived binding for the worker lifetime; web requests never start workers.

- [ ] Write fake-clock tests for 60/300/900-second schedules, duplicate/late commits, termination before commit, failed final reconciliation page, concurrent worker exclusion, source outage/recovery, merge/undo/hide/deletion and continuous import with bounded batches.
- [ ] Run `test_network_worker.py` for expected missing-worker failures.
- [ ] Implement durable refresh state, paged startup backfill, incremental lookback and scheduled metadata/full reconciliation. Diff fingerprints before projecting affected entities. Mark freshness stale on failed stages; partial reads never authorize deletion. Revalidate affected dependencies during reconciliation and preserve review audit events.
- [ ] Run worker/source/store/projection tests and a controlled isolated DB update → refresh → restart check. Confirm cursor cannot advance past a rolled-back derived batch and late commits are caught by lookback or full reconciliation.
- [ ] Commit Task 4 files with `feat: recover network updates across imports and restarts`.

### Task 5: Scoped extraction and durable review

**Files:** New `changes.py`, `test_network_changes.py`; modify `profiles.py`, store integration and extraction provider seam in `agent.py`.

**Interfaces:** `ProposalBatch` is a strict Pydantic model containing proposed entities, relations and profile assertions, each with source IDs/exact quote spans and binding dependencies. `validate_proposals(batch: ProposalBatch, snapshot: Snapshot) -> ProposalBatch`; `ReviewCommand(proposal_id: str, expected_version: int, decision: Literal['confirm','reject'], entity_bindings: dict[str, str])`; `PostgresNetworkStore.propose(batch: ProposalBatch, dependencies: dict[str, str]) -> int`; `review(command: ReviewCommand) -> int`.

- [ ] Write tests for fabricated quote rejection, ambiguous same-name binding, project mention without membership, unsupported relationship type, stale source version, rejected-proposal replay and restart. Assert proposed new entities/relations remain pending until exact source and identity bindings are confirmed.
- [ ] Run `test_network_changes.py` for expected missing-contract failures.
- [ ] Implement bounded extraction of explicitly selected messages and strict validation before persistence. Resolve new project identity during review; do not auto-merge names. Confirmed state feeds Task 3; source corrections invalidate eligibility without deleting review history. Default full-history extraction remains off.
- [ ] Run changes/profile/store suites with fake model; assert no pending or rejected proposal enters confirmed search/labels. Verify project activity describes evidence-backed events, not delivery/productivity scores.
- [ ] Commit Task 5 files with `feat: review source-backed network and profile proposals`.

### Task 6: Indexed retrieval and version-safe strategy answers

**Files:** New `index.py`, `service.py`, `test_network_index.py`, `test_network_real_agent.py`; modify `retrieval.py`, `agent.py` through dependency injection.

**Interfaces:** `IndexedRetrieval.people(terms: list[str]) -> dict`, `context(entity_id: str) -> dict`, `neighborhood(entity_id: str, depth: int) -> dict`, `pack(results: list[dict], requirements: list[dict], max_bytes: int = 28000) -> dict`. Preserve existing result envelopes: `people` returns people/contexts/unit_ids/terms; `context` returns entity_id/unit_ids/terms/mode; `neighborhood` returns paths/unit_ids/terms/depth/mode; `pack` returns records/evidence/paths plus coverage/budget/scope. Add truncation metadata rather than claiming bounded counts are corpus totals. `NetworkService.snapshot(query: GraphQuery, limit: int) -> Snapshot`; `search(query: GraphQuery, text: str, limit: int) -> dict`; `evidence(evidence_id: str, version: int) -> dict`; `validate(dependencies: dict[str, str]) -> bool`. Inject this retrieval/service seam into the agent; never build its planning catalog from a full-corpus `capture`.

- [ ] Write tests asserting server-side candidate/node/edge limits, deterministic pagination, parameterized hostile search input, non-Latin name fallback, hidden/pending exclusion, no whole-corpus catalog, 28000-byte context bound and a correction/merge/hide during provider delay. Add unrelated-new-message control case and unknown citation rejection.
- [ ] Run index/real-agent tests for expected missing implementations.
- [ ] Implement PostgreSQL indexed term retrieval and bounded adjacency queries; cap candidates before planning or materialization. Use built-in indexes initially, with explicitly bounded substring fallback where tokenizer coverage is weak. Return truncation/cursor indicators. No claim of full multilingual semantic coverage or new algorithm superiority.
- [ ] Implement actual source-dependency validation before model transmission and answer publication; refuse affected stale answers with retry guidance. Enforce configured session/extraction budgets and clear model unavailability/timeout responses. Preserve inspectable citations and unknown capability gaps.
- [ ] Run new suites plus `test_network_retrieval.py`, `test_network_intelligence.py`, `test_network_strategy_integration.py`; measure query plans on isolated large fictional fixtures to establish that limits precede context assembly.
- [ ] Commit Task 6 files with `feat: bound real network retrieval and validate answer sources`.

### Task 7: Real trial app and visible freshness

**Files:** New `scripts/network_real.py`, `test_network_real_app.py`; modify `scripts/network_demo.py`, network template and only required existing JS files from the file map. Add health/read-only inbox service methods to `service.py` as route wiring requires.

**Interfaces:** `scripts.network_demo.create_app(*, testing=False, llm_config=None, agent_provider=None, network_service=None)` preserves default synthetic behavior. `scripts.network_real.create_app(*, service: NetworkService, llm_config: dict, agent_provider=None)` requires real service. CLI `python -m scripts.network_real --env-file PATH --port PORT` binds loopback with debug off; missing schema/config/owner fails explicitly. `/network/health.json` returns version, freshness, source mode and sanitized dependency status.

- [ ] Write Flask integration tests for real inbox/contact/graph/evidence/search/agent/review, real-time query defaults, empty evidence states, pagination, SSE reconnect and loopback mutation protection. Assert `/network/demo/reply` and `/network/demo/reset` are absent in real mode, fixtures cannot load and failed config cannot become synthetic silently.
- [ ] Run `test_network_real_app.py` for expected missing real-app failures.
- [ ] Implement shared route wiring over the service, real read-only conversation slice and multi-label display. Show source mode, last successful refresh, truncation and pending evidence accurately; retain four scope controls and strategy subgraph interactions. Suppress demo controls in real mode. Preserve the user's CSS edit.
- [ ] Run app and existing demo/scope/strategy integration suites; browser-check real-mode interactions using fictional isolated records, including no-model mode and pending/confirmed transitions. Verify underlying source state remains unchanged after all UI actions except writes confined to derived state.
- [ ] Commit only Task 7 changes with `feat: expose persistent real network trial UI`.

### Task 8: Eva acceptance and Mark self-deployment package

**Files:** New `scripts/check_network_real.py`, `scripts/research/network_trial_benchmark.py`, `docs/demos/2026-10-02-real-network-validation.md`; update `docs/demos/2026-10-02-mark-local-delivery.md`, `runbook.md` and verified deployment skill copies.

**Interfaces:** `python -m scripts.check_network_real --base-url URL` reports sanitized health/route/citation checks, with no reset or source mutations. Benchmark outputs aggregate counts, workload/config/version, latency percentiles and resource/cost measures only. Never send real records to benchmark artifacts.

- [ ] Add a clean-checkout smoke test for required templates/static assets, CLI imports, missing config diagnostics and explicit initialization. Run it before packaging changes so missing resources fail visibly.
- [ ] Audit Eva's actual configured source read-only; record capabilities/counts and confirm source/owner binding. Prepare exact derived initialization/backup steps before performing authorized initialization; never substitute source migrations. Start worker and candidate on a checked free port.
- [ ] Validate real citations/identities/four scopes/labels/search; run a bounded selected extraction/agent probe only after basic data checks. Use isolated fixtures for destructive source corrections/deletions, observe actual real ingestion without inventing messages. Record actual runtime source freshness, restart, outage and review persistence.
- [ ] Measure graph/search/agent separately at Eva scale and a fictional workload matching at least Mark's reported 24,222 messages. Also vary topology/fanout/identity count and a larger stress size; message count alone is not load equivalence. Record cold/warm p50/p95, query plans, context/tokens, errors and limits; no unmeasured latency promise.
- [ ] Update the existing-Mac upgrade skill with tested checkout/install/config/schema/worker/app/health/stop instructions and exact shippable version. Preserve credentials and existing collectors; stop-trial rollback retains derived audit state. Mark must not need Eva's paths, data or newly installed Docker. Label Mac execution pending until observed on his machine.
- [ ] Run exact clean-install steps using the release layout; repeat only checks affected by new changes. Verify correct code/assets/skill are included in an accessible commit/release before marking deliverable. Keep release/upload authorization within the user's established scope; never claim unpushed files are delivered.
- [ ] Commit only reviewed release files with `docs: ship verified real network trial upgrade`; record remaining failures and Thursday readiness decision rather than marking unchecked tasks complete.

## Completion and research boundary

Completion requires a verified Eva candidate, a reproducible deployment package and an honest acceptance report; Mark's Mac verification is a distinct pending/observed result. No task here claims an experimental search method is better. After the first stable trial, freeze a reproducible research snapshot and follow the [two-track roadmap](../../papers/goal-directed-network-retrieval/two-track-roadmap.md).

Self-review (2026-09-30): all six delivery capabilities and deployment obligations mapped to Tasks 1–8; each Review Focus risk has an owning test. New types are defined above or in their producing task. No source migration, production restart, real extraction or performance measurement has been performed by writing this plan.
