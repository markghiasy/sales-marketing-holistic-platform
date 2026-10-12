# Unipile profile pilot and search status — 5 October 2026

## Verified today

Unipile `/accounts` returned HTTP 200. LinkedIn, Outlook and WhatsApp sources all reported OK. Connected accounts were created on 2 October in Sydney time. The public offer is a seven-day trial, but account creation timestamps do not establish the subscription expiry. The exact billing/trial deadline has not been verified.

The previous two-hour webhook experiment has stopped. Its local state records successful deletion of all three trial webhooks. That experiment was never a persistent production ingestion connector.

Source audit: 7,433 messages, 2,345 identities, 5,033 threads, 73 person rows and 922 LinkedIn connection snapshots. WhatsApp ingested a message on 5 October; the most recent stored Outlook message was ingested on 4 October and LinkedIn on 2 October. Later channel status files report successful Outlook sync on 5 October and LinkedIn sync on 5 October Sydney time. No new message does not necessarily mean a failed sync. Scheduler exit statuses include failures and need separate diagnosis; status files may only cover the ingestion stage, before downstream work.

The separate graph was version 9, last refreshed at 2026-09-30 16:18 UTC (1 October Sydney). No Network app or worker was running when inspected. Both were started hidden on 5 October, with the web app on loopback port 5059. The first smoke check rendered a real graph and verified two citations, but failed readiness because the graph was stale. A subsequent health read reported `source_unavailable` from the worker. Starting processes is not proof of recovery.

The background worker subsequently exited with database DNS-resolution failures. An independent read-only probe successfully loaded 18,234 retained records and a complete current source snapshot (32.816 seconds combined), so permanent loss of database access was not established. A retry was blocked by an orphan advisory lock. Inspection of the exact graph lock key found an idle Supavisor backend created at 00:35:31 UTC, during this worker's startup. Only that backend was terminated, guarded by its exact PID/start time, idle state and last advisory-lock acquisition query. The normal configuration uses the pooler on port 5432. Robust lease recovery and connection diagnostics remain operational work; no broad database sessions were terminated.

A subsequent one-pass refresh also exited with the sanitized `network_worker_unavailable` diagnostic. Final app health remained version 9, stale, `source_unavailable`. No successful publication or restored continuous ingestion is claimed. The page remains available for inspecting the retained snapshot; the worker is not healthy. The exact failure inside this later pass is not established by the sanitized CLI output.

## Three-profile pilot

Selected three reachable LinkedIn URL identities using decayed observed non-group message activity, prioritizing bidirectional interaction. This is a pilot ranking, not the production relationship score or a measure of competence. Existing person mappings were used; no fuzzy identity fusion was performed. Hidden contacts were excluded. The SQL compatibility probe needed explicit casts for heterogeneous source identifier types.

Requested experience, education and skills through the documented profile endpoint with visit notification disabled. The first API attempt timed out; a later bounded run succeeded. Requests were spaced apart and the runner stops on authentication/restriction/rate-limit responses or explicit section throttling.

| Pilot rank | Work experience entries | Education entries | Skill entries | Successful request seconds |
| --- | ---: | ---: | ---: | ---: |
| 1 | 7 | 2 | 0 | 2.899 |
| 2 | 14 | 5 | 40 | 5.688 |
| 3 | 7 | 1 | 18 | 4.312 |

All three returned HTTP 200 without a reported throttled-section list. This tiny sample does not establish reliability, completeness or freedom from account restrictions. Empty skills are unknown, not evidence that a person lacks skills.

Private snapshots are outside the tracked repository under `../tmp/unipile-profile-pilot-2026-10-05/`, with retrieval time, original URL, source identity binding and `profile_reported_unverified` status. Only aggregate findings belong in this report. No source person rows, message rows, graph claims or merges were written by this pilot. These profiles are not yet searchable in the production graph.

## Search optimization: implemented versus planned

Current production-trial retrieval uses PostgreSQL full-text search (`ts_rank_cd`), bounded entity/evidence selection, graph context and lexical evidence packing. It is not yet BM25 plus vector/HNSW hybrid retrieval. The assistant is bounded to two model calls: plan, then synthesize.

Previously implemented: database pooling, proof deduplication, bounded retrieval, removal of quadratic dependency work, and reuse of invariant lexical signals. The controlled same-input packing comparison improved from 6.1874 seconds to 0.0561 seconds. This does not establish end-to-end strategy latency.

A further local source-validation patch reduces independent read exchanges from nine to three while preserving a repeatable-read snapshot and source validation boundaries. Its published component test injected network latency; the patch is not yet committed. The last retained successful real strategy response remains 76.995 seconds, before a new controlled end-to-end comparison.

Today's first restored-service smoke check: health 1.024 seconds, graph 8.425, contacts 11.761, two citations 5.821/5.718, conversation 3.073, name search 10.031. These are individual measurements during worker recovery, not percentiles or an isolated before/after comparison. No model call was made today.

The agreed next sequence is:

1. Restore reliable source-to-graph refresh and expose stale/error states accurately.
2. Profile database acquisition, lookup, capture, validation, packing and model calls separately. Batch repeated reads and reuse version-bound intermediate results without bypassing permissions or fresh-source checks.
3. Add lexical/vector seed retrieval with rank fusion, followed by requirement-directed typed expansion under candidate, evidence and time budgets. Index profile snapshots asynchronously; do not fetch LinkedIn profiles inside an interactive strategy request.
4. Use evidence coverage, contradictions and unresolved requirements to decide which aspect to expand: project, capability, organization or strategic need. Record why each person and edge was included.
5. Return a useful candidate subgraph before the full narrative when supported by the UI/server; progressive strategy results remain planned. Compare quality, latency and cost against fixed baselines before claiming an algorithmic improvement.

Unipile improves the information available for retrieval. It does not directly eliminate database round trips or model-generation latency. Current measurements do not justify a graph-database migration as the first performance intervention.

## Sources and existing records

- [Official Unipile trial offer](https://www.unipile.com/pricing-api/).
- [Profile endpoint and section throttling](https://developer.unipile.com/reference/userscontroller_getprofilebyidentifier).
- [Prior latency diagnosis](../demos/2026-09-30-network-latency.md).
- [Real-network acceptance record](../demos/2026-10-02-real-network-validation.md).
- Local private probe results: `../tmp/unipile-current-status-2026-10-05.json`, profile pilot summary, and `../tmp/network-restored-check-2026-10-05.json` (paths relative to checkout parent).
