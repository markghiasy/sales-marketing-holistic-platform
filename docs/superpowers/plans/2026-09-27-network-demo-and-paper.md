# Network Explorer, Embedded Slice and Research Paper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a working English network demo in both the full explorer and existing Inbox detail layout, plus an evidence-grounded English supervisor paper and a five-minute presentation script.

**Architecture:** Preserve the existing app's production behavior. An isolated fixture-backed Flask app serves the existing Inbox template and a new explorer; both mount one graph component and query one deterministic graph service. Graphiti is a separately evaluated candidate behind the same identity/evidence boundary, not a mandatory dependency of the demo.

**Tech Stack:** Python 3.11+, existing Flask/Pydantic/pytest stack, vanilla JavaScript modules, locally vendored Cytoscape.js core, browser verification with available browser tools or Playwright, Markdown paper source and rendered PDF.

**Spec:** `docs/superpowers/specs/2026-09-27-network-graph-demo-design.md`

## Global Constraints

- English UI; discussion with Eva in Chinese.
- One ego, approximately 24 fictional contacts, three organizations, and two projects.
- Every screen carries a Synthetic demo label. Evidence text is fictional and labeled accordingly.
- No production database migration, live data backfill, outbound messages or live extraction in the presentation backend.
- Stable typed IDs, never display names, identify nodes and claims. Keep network owner distinct from focused contact.
- Default compact bounds: 8 nodes and 12 edges; explorer hard bounds: 50 nodes and 100 edges; at most two hops. Return omitted counts.
- Defaults for the demo: fast half-life 30 days, slow half-life 180 days, saturation scale 4 sessions. Reject nonpositive half-lives/scales.
- Group eligible direct messages into sessions when adjacent messages for the same contact/channel are no more than 30 minutes apart. Deduplicate source IDs before attribution or scoring.
- Pending claims appear only through an explicit hypotheses toggle; rejected claims never appear as supported edges. Unknown dates and missing channel coverage remain unknown.
- Future events are excluded from a historical query. Evidence known later cannot appear in earlier observation-time snapshots.
- No trust score, invented results, automatic publication, public deployment or claimed industrial validation.
- Keep approved research/spec files available in an isolated implementation checkout; preserve unrelated dirty files and do not copy credentials or private messages.

## Review Focus

- Rapid contact/filter switching must not let a late response replace the current selection: browser check in Task 4.
- Same display names and several roles between the same endpoints remain separately selectable: Tasks 1 and 4.
- Reset/reconnect while a detail inspector is open must converge to one current snapshot: Tasks 2 and 4.
- Long labels, empty graphs and keyboard-only use remain understandable at narrow panel width: Task 3 browser checks.
- A missing model/backend or failed extraction must be labeled unexecuted/failed, never converted into a successful benchmark: Tasks 6 and 7.

## Files and boundaries

| Path | Responsibility |
|---|---|
| `adapters/network/model.py` | Typed scenario, claim and query contracts |
| `adapters/network/projection.py` | Temporal eligibility, grouping, ranking and bounded snapshots |
| `adapters/network/scenario.py` | Synthetic scenario loader and versioned in-memory reply/reset operations |
| `scripts/network_demo.py` | Isolated server and fixture-backed Inbox API; no production app imports |
| `scripts/onboarding/static/network/graph.js` | Shared Cytoscape renderer; compact/explorer modes |
| `scripts/onboarding/static/network/client.js` | Query state, versioned refetch and SSE lifecycle |
| `scripts/onboarding/static/network/explorer.js` | Explorer filters, list, inspector and navigation |
| `scripts/onboarding/static/network/network.css` | Scoped shared graph/explorer styling |
| `scripts/onboarding/static/vendor/` | Pinned Cytoscape core, license and provenance file |
| `scripts/onboarding/templates/network.html` | Full explorer shell |
| `scripts/onboarding/templates/inbox.html` | Small opt-in demo configuration and shared component mount |
| `tests/fixtures/network_demo.json` | Public fictional entities, episodes, claims and named scenarios |
| `tests/test_network_projection.py`, `tests/test_network_demo.py` | Meaningful model/API tests |
| `scripts/evaluate_network_demo.py` | Reproducible fixture evaluation |
| `scripts/probe_graphiti.py` | Optional isolated backend probe |
| `docs/research/network-demo/` | Evaluation configuration, results and backend findings |
| `docs/papers/temporal-relationship-memory/` | Paper source, references, figures, rendered PDF |
| `docs/demos/network-explorer.md` | Run instructions and presenter script |

## Task 1: A reproducible evidence-backed graph

**Files:** Create `adapters/network/__init__.py`, `model.py`, `projection.py`, `scenario.py`, fixture JSON and `tests/test_network_projection.py`.

**Interfaces:**
- `load_scenario(path: Path | None = None) -> ScenarioData`.
- `GraphQuery`: `focus`, `view`, `as_of`, `search`, `function`, `organization`, `project`, `mode`, `include_pending`, `expand`; `view` is compact/explorer and `mode` is current/history.
- `build_snapshot(data: ScenarioData, query: GraphQuery, version: int) -> GraphSnapshot`.
- Snapshot fields: `version`, `computed_at`, `as_of`, `owner_id`, `focus_id`, `backend`, `nodes`, `edges`, `ranked_contacts`, `omitted_counts`, `truncated`. Claims and evidence use stable IDs; each returned edge names its claim and evidence IDs.

- [ ] Write tests for distinct same-name people, simultaneous roles, effective/observed dates, pending/rejected filtering, unsupported introductions, missing channel coverage and owner/focus separation.
- [ ] Add numerical tests asserting one session contributes 0.5 after its half-life, zero/future contributions are excluded, nonpositive scales fail, duplicate messages do not increase activity, CC/group messages do not masquerade as direct exchanges, and repeated one-way inbound does not become a reciprocal relationship.
- [ ] Add bounds tests asserting compact `len(nodes) <= 8`, `len(edges) <= 12`; explorer `<= 50` and `<= 100`; dangling edges absent; omitted counts accurate; compact/explorer overlap has identical claims and evidence.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_network_projection.py -q`; verify intended failures before implementing missing modules.
- [ ] Implement the contracts, fictional data and projection. Store review decisions and identity grouping as inputs, not inferred from display labels. Apply filters before the documented temporal ordering; break ties by stable ID. Keep relationship-history evidence as separate fields.
- [ ] Rerun the tests and require all to pass. Commit only this task's files.

## Task 2: Isolated server, coherent updates and Inbox fixture API

**Files:** Create `scripts/network_demo.py`, `tests/test_network_demo.py`; extend `scenario.py`.

**Interfaces:**
- `ScenarioStore.snapshot(query: GraphQuery) -> GraphSnapshot`, `reply() -> int`, `reset() -> int`, `wait_for_version(after: int, timeout: float) -> int`.
- `create_app(*, testing: bool = False) -> Flask` in the demo server, with no import of production `onboarding.app` or its monitor/connector side effects.
- Routes in the spec plus `/inbox`, `/inbox/conversations.json`, `/inbox/conversation/<person_key>.json`; fixture contact fields match the existing Inbox template. Unsupported production controls are visibly unavailable in demo mode.

- [ ] Test invalid focus IDs return 404, malformed times/views return 400, evidence IDs are checked, and all graph responses identify `backend=synthetic`.
- [ ] Test reply/reset strictly increase version, reset restores initial scenario content, snapshots are atomic, and SSE advertises version changes/heartbeat. Patch database/network connector entry points to raise if accessed; the demo must still serve its routes.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_network_demo.py -q` and confirm intended failures.
- [ ] Implement per-app store with a lock/condition; respond with complete snapshots and version-only SSE notifications. Bind CLI startup to `127.0.0.1`, default port `5055`; disable reloader. Initialize from fixtures without reading production credentials.
- [ ] Rerun model/API tests. Commit this task's files.

## Task 3: Full Network Explorer and reusable renderer

**Files:** Create the shared static modules, stylesheet, explorer template and vendored dependency/provenance.

**Interfaces:**
- `mountGraph(container, {mode, onNodeSelect, onEdgeSelect}) -> {setSnapshot(snapshot), fit(), destroy()}` exported by `graph.js`.
- `createNetworkClient({query, onSnapshot, onError}) -> {setQuery(patch), refresh(), destroy()}` exported by `client.js`.
- URL state encodes stable focus ID, filters, time and selected claim; input is parsed/validated rather than injected into markup.

- [ ] Read the frontend-design skill for visual execution. Use a clear workspace layout: compact toolbar, broad graph canvas, people list and evidence inspector. Use text labels plus shapes for entity types, and a clear selected-path treatment.
- [ ] Vendor one pinned Cytoscape.js core release from its official distribution, retaining license and recording version/source/hash. No runtime CDN. Use built-in layout facilities; avoid a new frontend framework or unrelated app restructuring. Official API reference: https://js.cytoscape.org/.
- [ ] Implement initial layout once per new neighborhood; preserve positions and viewport for selection/evidence updates. Support fit, pan, zoom, selected-neighbor expansion and resize. Show short edge labels; full claims belong in the inspector.
- [ ] Implement filter/list/inspector with source excerpts, review state and dates. Render text safely; provide a keyboard-accessible list/relationship inspector equivalent to canvas actions. Show request errors with retry and retain the last valid snapshot as stale.
- [ ] Start the local demo without a visible helper terminal and use approved browser tooling to exercise search, filters, node/edge selection, two-node/empty/dense cases, long labels and keyboard access. Record actual screenshots at desktop and narrow panel widths; fix observed overlap or unreadable labels.
- [ ] Require no browser console errors and no unexpected external requests. Commit this task's files.

## Task 4: Embed the same graph in the existing Inbox

**Files:** Modify `scripts/onboarding/templates/inbox.html`, `client.js`, `explorer.js`; extend `tests/test_network_demo.py`. Preserve the production route behavior.

**Interfaces:** The Inbox receives an explicit `network_demo` configuration from the isolated server; default absent means existing production behavior. Demo mode mounts `mountGraph(..., {mode: 'compact', ...})` with the selected `person_key`. The shared API uses opaque IDs throughout.

- [ ] Add route/template checks that demo mode loads the shared component and synthetic label, while the production default retains its current data path. Ensure contact/read/hide controls cannot call production routes through the fixture app.
- [ ] Implement compact graph mount/unmount in the existing detail slot. Add Open full network carrying query state; add an explicit Return to conversation navigation in the explorer. Keep graph selection separate from conversation navigation.
- [ ] Implement client request cancellation or generation guards; destroy prior graph instances/EventSources when closing or switching contacts. Refetch on SSE/reconnect and reject out-of-order older snapshots.
- [ ] Browser-check Inbox slice -> explorer -> original contact with matching focus/filter/time/evidence. Rapidly switch contacts and filters with delayed requests; the latest request must win. Select same-name contacts independently.
- [ ] Browser-check reply and reset with the inspector open; graph, list and evidence agree on the current version. Disconnect/reconnect and verify convergence. Confirm no accidental loss of current focus on simple selection.
- [ ] Run the targeted tests plus existing onboarding/inbox tests. Commit this task's files.

## Task 5: Evaluation artifacts and presentation package

**Files:** Create `scripts/evaluate_network_demo.py`, `docs/research/network-demo/scenarios.json`, generated `results.json`/`results.csv`, and `docs/demos/network-explorer.md`.

**Interfaces:** `run_evaluation() -> dict` produces named scenario results with `backend`, configuration, inputs, expected IDs, returned IDs, outcome and measurement status. CLI writes machine-readable outputs to the supplied output directory.

- [ ] Define expected answers independently from projection output for role change, simultaneous jobs, late evidence, ambiguous identities, several roles, cold inbound and task-driven contact discovery. Include a correction/rebinding scenario and undo that recomputes the projection; do not claim production merge integration.
- [ ] Compare three executed deterministic policies on the same fixtures: filter-only, filter-plus-recency, and typed temporal/context retrieval. Report contact inclusion, unsupported edges, temporal correctness and evidence-link correctness. Avoid claiming statistical generalization from this small constructed suite.
- [ ] Run `.venv\Scripts\python.exe scripts/evaluate_network_demo.py --output docs/research/network-demo`; inspect that every reported row is reproducible and identifies its policy. Keep unexecuted vector/Graphiti rows out of numeric results.
- [ ] Write startup/reset instructions and the five-minute script from the spec. Capture images showing the actual Inbox slice, full explorer, evidence and temporal change. Keep synthetic labels in screenshots.
- [ ] Commit the reproducible evaluation and presentation files.

## Task 6: Separate Graphiti feasibility findings

**Files:** Create `scripts/probe_graphiti.py` and `docs/research/network-demo/graphiti-probe.md`; isolate any dependency environment/store from the demo and production.

**Interfaces:** Probe accepts synthetic input path and explicit backend/model configuration; emits `status`, versions, configuration without secrets, observed behavior, evidence checks and costs/latency when available. `status` is executed/failed/unexecuted, never inferred from a successful import.

- [ ] Verify current official installation/provider requirements and available local tooling before installing. Inspect configured model availability without printing credentials. Do not start paid model calls unless their use and bounded budget are authorized; an unavailable prerequisite remains visible in the report.
- [ ] If runnable, test canonical UUID mapping and deduplication, simultaneous jobs versus employer changes, late evidence and source references. Use only synthetic episodes in a separate namespace/store; record versions and model settings.
- [ ] Test failure reporting with deliberately missing configuration; assert `status=unexecuted` and no benchmark score is emitted. Report extraction failures explicitly.
- [ ] Decide whether an adapter is supportable based on observed identity control, review-state separation and correction behavior. Keep integration out of the presentation path until those checks pass. Document unresolved questions rather than inventing results.
- [ ] Commit the probe and factual report. This task does not authorize a production migration.

## Task 7: Supervisor paper and final verification

**Files:** Create `docs/papers/temporal-relationship-memory/paper.md`, `references.bib`, `figures/`, `paper.pdf` and a small reproducible build script if required by the selected renderer.

- [ ] Revisit Eva's original mini-paper as input, preserving its relevant concepts. Draft the approved working title, research question, abstract, introduction, related work, model, architecture, evaluation, discussion and limitations. Target 6–8 pages excluding references unless the supervisor supplies a format.
- [ ] Verify bibliography from primary papers and official docs; distinguish Graphiti from hosted Zep, GraphRAG maintenance status, Hindsight's actual retrieval model and unverified TAPE details. Cite implemented capabilities separately from our design proposals.
- [ ] Add architecture and full/slice screenshots. Import only measured evaluation rows from Task 5 and appropriately labeled findings from Task 6. Do not claim superiority, industrial usefulness, biological fidelity or user-study results not established by the measurements.
- [ ] Read the PDF skill, render the PDF, inspect every page for clipping, references, readable figures and consistent captions. Keep the editable Markdown and reproducible source assets alongside it. No external submission or sharing.
- [ ] Run the complete existing test suite and relevant lint checks once after integration; if the environment blocks a required check, report the actual error and obtain the required execution permission. Perform final browser acceptance on both views after the last UI change.
- [ ] Use verification-before-completion and requesting-code-review according to the chosen execution workflow. Verify scope, evidence integrity, demo isolation and production default behavior. Resolve findings before delivery.
- [ ] Deliver the local demo URL/run instructions, presenter script, paper PDF/source and a concise list of implemented versus proposed capabilities. Commit only task-owned files; do not push/deploy/publish without scope authorization.

## Execution recommendation and current state

Recommended method: **Native** implementation in this session, followed by the workflow's independent final review. The renderer, query contract and host integration are tightly coupled; one implementer reduces coordination overhead for this prototype. Subagent-driven implementation remains an option if Eva prefers per-task independent review.

Native execution was approved and completed in `codex/network-demo-paper`. Tasks 1–5 and 7 have deliverables; Task 6 produced an explicit unexecuted prerequisite report rather than a live Graphiti experiment. The original granular checklist is retained as planning scope, not a claim that every suggested stress test was executed. See `docs/demos/network-verification.md` for actual verification, review findings, fixes, scope rulings and remaining research.
