# Real Network trial: implementation decisions

Full decision record from the autonomous implementation and independent review.
Read with the [acceptance report](2026-10-02-real-network-validation.md).

1. Ruling: skill bash helper cannot find basename in this Windows environment; use equivalent scoped ledger/brief files and native Python/PowerShell bookkeeping. Cost: maintain equivalent records manually; no product behavior change.

2. Task 1: Ruling: real source has multiple explicitly is_self identities not merged into one person. Use a binding-scoped virtual owner only when canonical self IDs differ; do not merge any source identities or contacts. Cost if source is_self flags are wrong: ownership attribution is wrong; visible source configuration remains authoritative.

3. Ruling: incremental allowance is split between forward cursor progress and bounded lookback replay; full reconciliation covers older or crowded-window late commits. This avoids replay starving all new imports.

4. Task 2: in progress. Ruling: retain existing disposable DB guard, add serialized literal network schema fixture and share source fixture via conftest.

5. Task 2: Ruling: Projection belongs in store.py to avoid a circular dependency; apply accepts optional Projection so snapshot staging and store tests can run before real projection is implemented. User-visible worker commits will pass projection in the same transaction.

6. Task 2: Ruling: derived writer uses a NOLOGIN PostgreSQL role and initialization refuses inherited/PUBLIC source-write privileges. Creating the role requires deployment preflight; no permission escalation or source-grant modification occurs automatically.

7. Task 3: Ruling: projection accepts binding as an optional keyword to produce the same binding-scoped virtual owner as source audit. Existing canonical person IDs remain unchanged for other people.

8. Task 4: Ruling: first trial uses a bounded worker-only source cache (100000 records/256 MiB payload default), rebuilt from durable mirror on restart; only changed people's message neighborhoods are projected for ordinary incremental updates. Metadata identity/visibility changes trigger complete reconciliation to avoid mixed bindings. Costs: memory limit must be measured and full metadata reconciliation can be more expensive; oversized source fails without partial publication.

9. Task 4: Ruling: full snapshot pages accumulate under explicit bounds and publish once; interrupted snapshots are retried from the beginning, retaining the prior consistent derived revision. This trades resumable mid-snapshot backfill for a simpler correctness boundary in the trial.

10. Task 5: Ruling: split transactional proposal handling into review_store.py to avoid overloading store.py; store exposes the planned propose/review interfaces. Proposal prerequisites include review-version dependencies as well as source fingerprints, so a rejected prerequisite cannot silently remain supported.

11. Task 5: Ruling: use a separate real selected-source extraction method, preserving the synthetic extraction contract. It only emits proposals; UI hookup follows in Task 7. Provider was fake in all new extraction tests; no real model calls yet.

12. Task 7: Ruling: real factory lives in scripts/network_real.py and is injected through network_demo.create_app; shared templates/assets with separate real routes prevent fixture fallback and demo mutation endpoints. Real contact pagination is explicit; activity metrics disclose loaded-message coverage, not corpus totals. Live date mode advances on revisions; historical identity revisions are not reconstructed.

13. Final: Ruling: accept entity-only queue, evidence fanout and Flask-minimum findings as Important; fix persisted context associations/legacy lookup, three-source pages with independent failures, Flask>=3.1 plus hostile-Host regression. Cost if wrong: missing review paths or slower first source page; preserving private-host boundary is required.

14. Final: Ruling: regrade recent-message UUID sampling from Minor to Important because a normal new Inbox update can be absent indefinitely and last_message_at misleading. Select latest messages before the bound with historical as-of filtering and deterministic ID ties; source history remains explicitly incomplete. Cost: changed sample order, not evidence or identity inference.

15. Final: Ruling: reviewer set aside scientific novelty/effectiveness; research remains the second active goal and no algorithm claim is made. Cost: research not yet ready for submission.

16. Final: Ruling: dense retrieval, database replacement, project management and automatic outreach remain outside this trial; no promised trial function depends on them. Cost: later enhancement work.

17. Final: Ruling: historical identity reconstruction and complete activity totals stay unsupported and disclosed; current source identity mapping is authoritative. Cost: historical entity-level views are not archival reconstruction.

18. Final: Ruling: complete source checkout is the shipping contract; wheel-only install is unsupported. Clean checkout tested. Cost: deployment must retain assets/sql alongside modules.

19. Final: Ruling: trial remains loopback/foreground; public hosting, multiuser auth and service management require separate design. Cost: operator runs two foreground commands.

20. Final: Ruling: legacy general deployment migration-skipping remains outside this Network branch; Network guide prohibits source migrations and duplicate skipping. Cost: general-upgrade skill needs separate cleanup before reuse in that scope.

21. Final: Ruling: private semantic acceptance, latency, accessible release and target Mac are not waived by code review. Continue real/clean checks; target Mac stays explicitly pending until observed. Cost: release readiness may remain conditional.

No reviewer Minor remains deferred: the newest-message sampling issue was regraded and fixed because it affected normal Inbox updates.
