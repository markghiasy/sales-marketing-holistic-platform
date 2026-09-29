# Mark local Network trial — delivery record

Target: Friday 2 October 2026. Updated 30 September. **Local runtime and clean-install checks passed. This is a controlled trial
candidate, with slow strategy responses and target-Mac verification pending.**

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
collectors and earlier candidates were retained. Real hosted-database latency remains
variable and must not be described as solved.

See the [acceptance record](2026-10-02-real-network-validation.md) for measured
results, encountered failures, limits and remaining gates. The
[upgrade guide](network-trial-upgrade.md) covers the exact source-checkout layout,
separate environment, existing credentials, derived-only initialization, worker,
loopback app, smoke checks and stop-with-audit-retained rollback.

## Release revision

- Candidate release ref: **`network-trial-2026-10-02-rc1`**. Resolve it after
  `git fetch origin --tags`; do not substitute an unrelated branch or source DB.
- Release branch: `codex/network-demo-paper` in
  [the existing repository](https://github.com/markghiasy/sales-marketing-holistic-platform).
- Tested runtime revision: `1d5e93f`; subsequent release documentation changes
  do not change the runtime. The tag includes the complete source checkout and
  both `.claude` and `.agents` deployment skill entries.
- Windows: **579 tests passed**, lint passed, and an independent clean archive
  installed successfully (pip exit0, dependency check clean, source-local imports,
  templates/static/SQL/skills present, all four CLIs reject missing configuration).
  The clean environment used Python3.12.10, Flask3.1.3 and psycopg_pool3.3.3.
- GitHub checks: verify the candidate's
  [Actions results](https://github.com/markghiasy/sales-marketing-holistic-platform/actions?query=branch%3Acodex%2Fnetwork-demo-paper)
  and tag availability before deployment. A local test run is not a remote CI run.
- Mac execution and Mark-specific source acceptance: **pending on his machine**.

The updated Eva candidate is at `http://127.0.0.1:5059/network`. This loopback URL
is for Eva's computer only. Mark starts his own app against his existing env.
No source credentials or private messages are included in the release artifacts.

Known trial costs: Eva's last graph/name requests took about5.6/6.3seconds;
the latest strategy answer took about77seconds, with a bounded, cited result.
Her derived schema occupied about292MB including indexes. These observations
are not response-time guarantees or storage estimates for Mark. Check his
provider quota first. Read the acceptance report before presenting the trial as
production-ready; the research algorithm is not part of this release.

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
