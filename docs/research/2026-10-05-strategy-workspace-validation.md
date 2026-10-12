# Progressive Strategy workspace: implementation and validation

This increment separates goal analysis from ordinary contact search. It implements a bounded experimental cycle: requirements, parallel candidate retrieval, evidence assessment, one gap-driven search round, then a refreshed set of conditional options. It does not establish a new optimal search algorithm or production latency improvement.

## Product and execution model

1. `/strategy` has a dedicated goal form, task progress, incremental subgraph, evidence, requirement assessments, alternative combinations and dependency-ordered actions. Search hands over a draft privately and requires an explicit start.
2. Up to three independent retrieval workers run concurrently. These workers execute bounded read-only tools; they are not independent paid Claude conversations.
3. At most three model calls perform planning, gap assessment and final synthesis. Initial recall is bounded to four planned lookups plus one supplemental lookup; follow-up is bounded to three searches and one round.
4. Results appear through server-sent events. Reload/reconnect replays the existing run without another model call. Failed or cancelled analysis preserves validated partial results; revoked or unverifiable evidence clears them.
5. The local process retains up to eight runs for 30 minutes, with a 180-second run budget and bounded event memory. App restart loses these runs. In-flight synchronous requests cannot be forcibly terminated; cancellation blocks subsequent work and discards late output.

Automatic alternative elimination is deliberately unavailable until typed constraint checks or explicit human decisions exist. Novel follow-up candidates receive a deterministic reserved share of the node/source budget, interleaved across branches; this is a capacity policy, not optimized combination selection.

Historical evidence, insufficient evidence and potential conflicts are distinguished from current willingness, availability and authority. Inferred requirements remain suggestions. Missing evidence does not prove missing ability. Mechanical quotation and source-binding checks do not prove semantic entailment.

## Measured behavior

### Controlled concurrency benchmark

Five repetitions of three independent retrieval tasks, each delayed by 150 ms, produced identical results:

| Sample | Serial seconds | Parallel seconds |
| --- | ---: | ---: |
| 1 | 0.4530 | 0.1522 |
| 2 | 0.4519 | 0.1512 |
| 3 | 0.4520 | 0.1512 |
| 4 | 0.4520 | 0.1512 |
| 5 | 0.4517 | 0.1516 |

This verifies overlap of independent waits. It is not a measurement of the remote database or model, and does not imply a threefold end-to-end speedup.

Reproduce with `python -m scripts.research.strategy_concurrency_benchmark`; the script reports both first partial and total times and checks result equality.

### Live-provider compatibility

A fictional-only Claude Haiku 4.5 smoke test exposed a real API incompatibility: the nested alternative/evaluation schema exceeded the provider's compiled strict-grammar limit. Making every nested field required did not resolve it. The two complex evaluation tools therefore use forced tool submission without provider grammar compilation; local Pydantic bounds, quotation checks, entity/subject bindings and dependency checks remain mandatory. Existing simpler tools retain strict mode. Invalid quotations and subject/context bindings are never accepted as facts. Live fictional outputs also exposed uncited support labels and combinations assigning a venue observation to recruitment; these require proposal-level validation and explicit incomplete-result presentation, rather than trusting successful JSON generation.

The new evaluation calls have a maximum of 5,000 output tokens each, while planning/legacy calls remain capped at 3,000. Compact-output instructions bound practical verbosity. This increases the worst-case three-call output allowance to 13,000 tokens; it does not guarantee lower total latency or spend.

Anthropic documents the interaction between optional fields, nesting and compiled grammar complexity, and recommends reserving strict tools for cases that need them: [structured output limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). This compatibility change is based on the observed rejection plus local validation tests, not a relaxation of source-access checks.

### Replay validation cost

For a retained run with five successive merged partials and one completion, replay now delivers only the latest partial. The controlled regression requires two delivery-time source checks, one per delivered evidence payload, compared with seven before coalescing and removal of a duplicate blanket check. Plans, task labels, assessments and completion still require their own checks when delivered. Reconnect after the last event also checks retained evidence.

## Remaining performance and release work

- Measure first useful evidence, assessment time, final time and provider usage separately. An extra reasoning call may increase final latency even while staged output improves time to usable evidence.
- PostgreSQL full-text ranking and bounded graph traversal remain the retrieval backend. No embeddings, HNSW, BM25 or graph database migration were added.
- Independent branches still materialize source slices and the coordinator recaptures the merged slice. Source validation and remote database round trips remain potential dominant costs; do not remove disclosure checks merely to make a benchmark faster.
- The disposable PostgreSQL integration suite requires an explicit local `TEST_DATABASE_URL`. Production data must not substitute for it.
- Production projection freshness and a persistent ingestion worker are separate from this UI/algorithm increment. A successful fictional demo does not certify current private-data coverage.
- Future evaluation should compare one-pass retrieval, parallel one-pass retrieval and the bounded gap loop on the same fictional goals. Measure requirement evidence coverage, unsupported assertions, useful contact paths, candidate diversity, cost and first-result/final latency; do not tune only for visual graph size.


## Final verification record

- 170 focused non-database Python tests passed in 5.05 seconds.
- 38 affected browser tests passed in 107.37 seconds, including actual Flask/EventSource transport, early partial visibility, no extra model call on reload, cancellation, invalidation, safe follow-up history, mobile layout, stable graph positions and incomplete-validation notices.
- Independent reviews found and drove regressions for revoked task labels, saturated follow-up budgets, lost retrieval failures and unsupported elimination. The final clarification field is cleared with other unvalidated prose in a partial answer.
- Source-backed proposals are validated independently. Invalid assessment rows, complete invalid combinations and invalid follow-up tasks are excluded. Diagnostics contain counts/flags only. Earlier options are retained only if they still validate against the final evidence pack.
- A malformed/uncited finding is omitted before final model parsing and marks the answer incomplete; no uncited finding becomes a fact.
- No disposable PostgreSQL integration suite was run. No production source records, profile assertions or graph relationships were written by this increment.

### Fictional live-provider observations

The fresh three-call attempt returned its first candidate subgraph at **6.875 seconds**, an initial assessment at **42.890 seconds**, and preserved these when final parsing rejected an uncited finding at **73.265 seconds**. This failure motivated finding-level isolation. These timings describe a tiny fictional dataset and must not be compared directly with the earlier private-data 76.995-second measurement.

After that correction, the recorded live planning and assessment outputs were reused through the same retrieval pipeline, and a **new live final-synthesis call** completed in **36.125 seconds** (10,314 input tokens, 3,759 output tokens). It returned **7 checked assessments, 2 conditional alternatives and 7 pending constraints**, with no rejected proposals in that final response. This is a provider-integration smoke test with replayed earlier stages, **not** a fresh end-to-end latency benchmark or a reliability estimate. A separate all-recorded replay also completed without API calls.

Multiple earlier live attempts exposed strict-grammar compilation limits, missing citations, wrong subject bindings and unsupported assignments. Successful source checks do not establish semantic correctness or production readiness. Further controlled evaluation of proposal acceptance and task usefulness is still required.

## Try the local experimental build

The synthetic demo is served at `http://127.0.0.1:5058/strategy`. Start an analysis explicitly; entering from ordinary search does not spend a model call. The default network is the existing fictional business scenario, not a copy of private contacts.

From this worktree, an equivalent foreground development command is:

```powershell
& '../repo/.venv/Scripts/python.exe' -m scripts.network_demo --port 5058 --env-file ../repo/.env
```

Do not start a second process on the same port. The running demonstration was launched hidden; its exact process metadata is in the local ignored `tmp/strategy-demo-runtime.json`. This is a development preview, not an installed production service.

## Default-scenario failure and correction (5 October, follow-up)

The user's AI-workshop query failed on the default business scenario. The earlier tiny workshop fixture did not establish readiness for this dataset. Reproduction found a gap-assessment response truncated at 5,000 output tokens. After compacting that response, final synthesis exposed redundant input exceeding the 18,000-token input cap. A subsequent browser attempt exposed another failure: otherwise structured output supplied legacy `gaps` and `next_steps` as strings instead of lists.

The provider wire contract now asks for evidence IDs and assessment IDs rather than repeated source quotations, statements, and assignment bindings. The application attaches exact source excerpts (up to 1,000 characters), derives assignment subject/requirement from the referenced assessment, and still applies local schema, source-binding and dependency validation. Source excerpts prove provenance, not entailment or goal suitability. Previous comparison prose and duplicate record quotations are omitted from the input; evidence, pending constraints and action dependencies remain. Final legacy sections are derived from the structured evaluation rather than generated twice. Unsupported proposal units are omitted with visible incomplete-result diagnostics. Input/output limits now have safe, specific failure messages.

Fresh browser verification used the exact query `IM PLANNING FOr ai workshop/ who should i rech out to what shoould i do`, the default synthetic scenario, actual EventSource transport, and three fresh live Claude calls. It returned a first subgraph at **7.91 seconds**, an initial assessment at **36.16 seconds**, and a completed response at **57.58 seconds**. The retained result contained **5 assessments, 1 conditional option and 6 pending constraints**, with no browser JavaScript errors. One final proposal was omitted and earlier-stage omissions remained disclosed: this was a completed partial assessment, not a fully accepted or production-certified answer. Total usage was **31,594 input / 5,945 output tokens** across the three calls. This is one observed run, not a latency or reliability guarantee.

The 100 focused non-database regressions passed; the 19 affected Strategy browser regressions passed. Ruff and whitespace checks passed. No production data or database integration tests were used. Remaining work includes improving proposal acceptance, capability relevance, and conditional-path language; the default business network does not establish AI-workshop teaching expertise merely through research or engineering labels.
