# Identity upgrade validation and decisions

Base: `1337533`. Isolated worktree: `identity-cluster-worktree`; branch: `codex/identity-cluster-review`.

User authorized implementation and push, with no repeated stage confirmations. Mark's file was initially absent from Downloads; it appeared during inspection and was read in full. Both diffs passed `git apply --check` against the base.

## Execution record

- Baseline: 360 tests passed. Initial 44 setup errors were caused by the new worktree lacking the `.tmp` parent for the specified pytest basetemp; creating the parent resolved them. No production change was needed.
- Policy tests: observed 5 failures before implementation; 53 relevant tests passed after policy and 0013 changes.
- Cluster tests: 8 failures before implementation; 10 cluster/reply tests passed afterwards.
- Brief/API tests: 5 failures before implementation; 103 brief/inbox/contact/route tests passed afterwards.
- Folder tests: 5 failures before implementation; 49 Outlook tests passed afterwards. Added explicit page-following coverage.
- Provenance tests: 2 failures before implementation; 6 provenance/runner tests passed afterwards.
- First full suite: 382 passed in 80.83 seconds; Ruff clean.
- Bounded refresh command: 2 failures observed before implementation. Final results recorded below after review.

## Rulings

1. Native inline implementation with one final independent reviewer follows the user's autonomy request. Work is isolated from existing user changes; push is authorized, production deployment is not performed here.
2. Mark permits adapting his patches. Resolve built-ins by ID, remove the silent depth cutoff, use existing request retry handling, filter drafts and defer checkpoint publication until commit. Cost: additional folder-metadata requests when all-folder scope is enabled.
3. Count confirmed identity equivalence toward component density and every identity toward its size. Reject/retired/self/hidden boundaries are conservative. Cost: some useful ambiguous clusters remain unaggregated.
4. Invalidate all cached briefs on candidate topology/hide changes, but use per-identity revisions for message/fact changes. Cost: unrelated briefs may require regeneration after an identity decision. This avoids stale uncertain attribution without adding a materialized cluster-maintenance subsystem.
5. Keep candidate message bodies/facts out of the confirmed contact's prompt; only statistics are conditional. Cost: the brief cannot summarize a suspected second identity's content until a human resolves it.
6. Main-production fixes and network-trial PR #4 remain separately reviewable. Cost: the trial needs integration before sharing these behaviours.
7. Delivery includes a bounded dry-run-first refresh command because no shared brief-backfill CLI existed. No live paid backfill is executed.

No production `.env`, API keys or message contents are included in this branch. Tests use an explicitly disposable loopback PostgreSQL database and mocked providers.
