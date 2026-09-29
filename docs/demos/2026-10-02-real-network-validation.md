# Real Network trial — acceptance record

Work in progress, 2026-09-30. This record separates verified behavior from
remaining gates. It is not yet a release sign-off.

## Verified so far

- Eva's configured source was audited read-only: 7,343 messages, 2,342 identities,
  73 canonical persons, 5,015 threads, 731 organizations, 1,784 facts, 922 LinkedIn
  connection snapshots, eight hidden contacts and 13 self aliases. Counts are
  source records, not claims about visible contacts or verified relationships.
- A new, separately bound `network` schema and restricted non-login writer role
  were explicitly initialized. Source tables and existing collectors were not
  migrated or restarted. Unknown schema versions and other source bindings fail.
- Source/store/projection/worker tests exercise replay, correction, deletion,
  merge/undo, manual hiding, out-of-window late commits, interrupted snapshots,
  source outage/recovery, writer exclusion and review persistence with fictional
  PostgreSQL fixtures. An isolated dump/restore retained audit and source binding.
- Source-linked real-mode agent tests use a fake provider to check context bounds,
  source changes during generation and the unrelated-update control case.
- The real app exposes graph, four scopes, contact slice, pagination, source
  inspection, selected extraction and durable proposal review. Real mode has no
  scenario-reset/reply routes or fixture fallback. No-model operation is tested.
- Latest UI verification: 19 real-app/demo-browser tests passed. A later 37-test
  projection/worker/review/agent/app run passed after fixing the dependency growth
  issue below. These are actual isolated/local tests, not Mac results.

## Problems found by acceptance, not hidden

The first real backfill revealed repeated contact-history dependencies on every
message. A 200-message regression produced 83,217 dependencies. Message bindings
were separated from the contact's visibility proof, making that workload linear.
The interrupted real write rolled back: version zero and zero published mirror
rows were verified. The corrected backfill published version 1 successfully;
the source snapshot-to-publication interval was about 251 seconds. Existing
source content was unchanged by the trial. A continuous worker has subsequently
refreshed its source-check timestamp without inventing changes or revisions.

The browser also caught an unknown-channel rendering crash and an old profile
validator rejecting confirmed proposals' review pointer. Both received regression
coverage and were fixed before real UI acceptance.

Real acceptance also found name search still using the synthetic owner ID, and
a larger group-message workload returning an empty evidence pack. Both have
regression fixes: real search uses its bound owner, and authored group-message
passages can be retrieved as observations without inventing interpersonal edges
or verified capabilities. The empty-pack benchmark is a failed probe, not a
passing speed measurement.

A read-only HTTP smoke run against Eva's real version 1 passed on port 5058:
50 displayed nodes, 26 edges, ten sampled contacts and two version-bound source
citations. Health was fresh and error-free; the view correctly reported
truncation. The configured provider was `claude-haiku-4-5-20251001`.

## Performance evidence

The initial fictional local PostgreSQL workload used 24,222 short messages,
2,000 contacts, one thread and ten queries. Before the dependency fix:

| Measurement | Observed |
|---|---:|
| First backfill | 159.911 s |
| First retrieval | 2.226 s |
| Retrieval median | 1.972 s |
| Retrieval p95, ten samples | 2.626 s |
| Largest evidence pack | 27,492 bytes (28,000-byte cap) |

The sample EXPLAIN plan used the `network_item_search` bitmap index. These numbers
include candidate retrieval and context preparation, **not LLM generation**.
They are not hosted-source measurements or a universal scalability claim.
Revised/concentrated/multiparticipant stress results and Eva request timings are
pending below; supersede the old measurements only after actual runs finish.

Real hosted-database latency remains a release concern. An initial instrumented
graph call took 13.32 s, with about 7.67 s in three connection/setup operations.
The new process-local pool and batched section query produced independent graph
measurements of 5.806 s and 4.571 s. However, a separate full HTTP smoke observed
25.966 s for graph and 41.354 s for name search. These are different runs, not a
controlled speedup claim; investigate variance before promising responsiveness.
Source transactions retain explicit read-only/repeatable-read boundaries and
writer roles reset between pooled transactions, verified by PostgreSQL tests.

The corrected stress run used 48,000 messages, 3,000 identities, four participants
per message and 80% of messages concentrated on one author. Backfill took
207.501 s. Six non-empty-evidence retrievals measured 2.317 s first, 2.255 s median
and 2.464 s p95 (the largest of six samples). The largest pack was 27,302 bytes.
Derived dependencies occupied about 535 MB for 1,314,004 rows and items about
170 MB. This exposes a real storage cost even though the dependency growth bug
was fixed. It is not equivalent to every possible 48,000-message customer corpus.

Three subsequent real HTTP graph requests took 11.662 s, 6.554 s and 5.531 s,
all HTTP 200. The first-call and hosted-network variation remain visible; no
subsecond latency promise is justified.

## Remaining release gates

Verification update: 568 tests passed in 253.69 s. A subsequent transport
regression demonstrated twenty copies of shared proof crossing the DB connection;
the store now deduplicates on the server using the existing composite index and
rejects conflicting versions rather than choosing an arbitrary one. Eighteen
store/index/agent tests passed after that change. A clean archive of `03995b7`
installed into a fresh Windows virtual environment; dependency check, imports
resolved inside that checkout, runtime assets and missing-config refusal passed.
The PowerShell wrapper reported an error for pip's update notice on stderr, so
installation was independently checked rather than assumed failed or successful.

One real Claude strategy query returned HTTP 200, three findings with two distinct
cited sources, and a ten-node strategy subgraph. It used 15,377 input and 943
output tokens across planning and answering, with a 27,882-byte evidence pack.
Total latency was **232.898 s**, which is not acceptable interactive performance.
A separate deterministic no-model, two-lookup diagnostic took 49.093 s, including
repeated retrieval and actual-source validation. It is not the same plan, so the
remainder cannot be assigned to Claude by subtraction. Further profiling remains
a release gate. The provider was Haiku 4.5; no source content is reproduced here.

- Repeated Eva latency measurements and broader real interaction checks.
- Selected-source extraction probe and strategy latency improvement; inspect
  grounding without publishing private source content.
- Larger and varied-workload benchmark, full branch regression suite, clean
  checkout/install and fresh whole-branch review.
- Exact accessible release revision, synchronized deployment skill, restart and
  refresh evidence, and completed delivery record.
- Mark Mac execution: pending target-machine testing. The deployment guide is
  prepared for a Mac with existing Ironman; local Windows checks do not prove it.

No private names, source messages, prompts or credentials belong in this report.
