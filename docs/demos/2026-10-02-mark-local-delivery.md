# Mark local Network trial — delivery record

Target: Friday 2 October 2026. Updated 30 September. **Release readiness is still
under verification; this is not a target-Mac deployment sign-off.**

Mark has an existing Ironman installation on Mac and wants to test the Network
demo's functions using his already ingested data. The agreed path is Eva's local
real-data validation, then an updated deployment skill for Mark to self-deploy.

## Implementation status

The candidate now reads the existing source through a database-enforced read-only
adapter and publishes versioned derived state in a separate PostgreSQL `network`
schema. It includes persistent proposals and review history, four relationship
scopes, source-linked search and strategy answers, multi-label contact views and
a polling/reconciliation worker. Synthetic reset/reply routes are absent in real
mode. Unsupported projects, capabilities and introductions remain unknown until
supported by reviewed evidence.

Eva's corrected first backfill has published version 1. A read-only HTTP smoke
verified graph, contact slice, conversation, name search, two citations and fresh
health. The updated candidate is running separately on port 5058; existing Inbox,
collectors and earlier candidates were retained. Real hosted-database latency is
still variable and must not be described as solved.

See the [acceptance record](2026-10-02-real-network-validation.md) for measured
results, encountered failures, limits and remaining gates. The
[upgrade guide](network-trial-upgrade.md) covers the exact source-checkout layout,
separate environment, existing credentials, derived-only initialization, worker,
loopback app, smoke checks and stop-with-audit-retained rollback.

## Release revision

- Local implementation: `03995b7` on `codex/network-demo-paper` (includes the
  preceding source, store, worker, review, UI and pooling changes).
- Accessible release revision: **pending final verification and publication**.
- Clean source checkout/install: in progress.
- Whole-branch regression and fresh review: in progress/pending.
- Real provider probe and latency acceptance: in progress.
- Mac execution: **pending on Mark's machine**.

Do not use a local-only hash as evidence that Mark can fetch a release. The final
record must name the accessible revision after checks complete. No source
credentials or private messages are included in these artifacts.

## Acceptance on Mark's Mac

1. Audit his source binding and configured self identity; do not copy Eva's env.
2. Initialize/check only the derived schema; keep his current source and
   collectors running. A complete initial backfill must publish atomically.
3. Verify known identities and original-message citations in the graph and Inbox.
4. Exercise the four relationship scopes and distinguish shared affiliation from
   direct interaction or a documented introduction.
5. Search for a known contact; ask a strategy question and inspect citations and
   unknown requirements. The evidence pack must remain bounded.
6. Extract from explicitly selected sources; leave proposals pending until the
   operator reviews them. Rejection and confirmation must persist across restart.
7. Observe a normal import and freshness/version updates. Use fictional fixtures,
   not customer records, for destructive correction/deletion fault tests.
8. Stop the separate trial app/worker if necessary, retaining audit state and
   leaving the original application available.

## Product and research boundary

The [two-track roadmap](../papers/goal-directed-network-retrieval/two-track-roadmap.md)
keeps the first usable release independent of the proposed research algorithm.
After stability checks, freeze a reproducible research revision and compare
multi-requirement retrieval methods under equal budgets. Customer satisfaction,
a working graph and engineering benchmarks are not paper results.
