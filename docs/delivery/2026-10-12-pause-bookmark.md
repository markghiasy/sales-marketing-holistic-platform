# Ironman — version-specific pause bookmark
**Prepared for Mark · 12 October 2026**

This preserves the earlier version-focused handover. For the complete project and requirements assessment, start with [the project summary](../../handover.md). The later repair at `a765ab9` passed [all 663 tests in CI](https://github.com/markghiasy/sales-marketing-holistic-platform/actions/runs/38206178002); earlier local-only verification counts below remain historical.

Mark — this is the bookmark for what we have built so far: where the code lives, what each part does, how to inspect it, and what remains unfinished. The project remains paused. This handover preserves the current work; it is not a production release sign-off.

## 1. Where the work lives

Repository: https://github.com/markghiasy/sales-marketing-holistic-platform

| Delivery | Location | Status checked 12 October |
| --- | --- | --- |
| Resolution quality, merge attribution, brief failure visibility and SDK compatibility | [PR 2](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/2), [PR 3](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/3); merged revision `13375331b134ffba53ca6c77828889dcc7258b3a` | Merged. Your earlier feedback confirmed applying migrations 0010–0012 locally. |
| Network explorer and real-data trial | [PR 4](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/4), `codex/network-demo-paper`, revision `50ce177afcf27a9902da86c92491cea949d1dfca` | Open draft; separate trial, not merged or accepted on your Mac. |
| Provisional identity suggestions and filed-mail upgrade | [PR 5](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/5), `codex/identity-cluster-review`, revision `6543a8814670687229b8e31deae1c71d28068bf1` | Open; separate from PR 4. |
| Additional Strategy workspace and performance work | `codex/ironman-pause-handover` — this branch | WIP snapshot built on the PR 4 revision above. Adds the previously local increment, tests and engineering reports. |

This branch does **not** include PR 5. The two product branches have not been integrated into a single release. Do not treat checking out this handover branch as installing the identity upgrade.

## 2. What is available

1. **Existing ingestion and Inbox.** The existing platform ingests Outlook, WhatsApp and LinkedIn into the shared store. The Inbox has cross-channel threads, contact editing/linking, hide/unhide, AI briefs and live-refresh support. Availability still depends on the configured collectors and local processes.

2. **Identity quality and auditability.** The merged fixes retire the unreliable name-only LinkedIn rule, attribute merge decisions, expose brief-generation failures and isolate database tests. PR 5 implements your subsequent policy: exact-email is the only automatic-merge-eligible signal; heuristic matches remain evidence-backed suggestions. Provisional aggregation is bounded to components of at most eight identities with at least 50% edge density. It also retires signature-phone candidates, adds brief invalidation dependencies and records resolution-run provenance.

3. **Filed Outlook mail.** PR 5 includes opt-in recursive folder discovery with `OUTLOOK_FOLDER_SCOPE=all`, exclusions and checkpoint handling. It requires its documented migration/upgrade steps; the existing default remains Inbox and Sent Items.

4. **Network exploration.** Full graph and conversation-level slices, light styling, multi-label contacts, filtering and evidence inspection. Four relationship scopes distinguish direct interaction, documented collaboration/introduction, shared project/team and shared organization/company. Affiliation is context, not proof that people know one another.

5. **Profiles and strategic discovery.** Evidence-backed profile proposals can be reviewed before becoming confirmed graph assertions. The assistant retrieves people, organizations, projects and supported paths for a goal, with source references and unresolved requirements. A past role does not establish present availability or willingness.

6. **Independent Strategy workspace — new WIP.** `/strategy` separates longer goal analysis from ordinary contact search. It plans requirements, runs up to three bounded retrieval workers concurrently, assesses coverage, performs at most one gap-driven search round and returns conditional options/actions. The workers are read-only retrieval tasks, not three independent paid agent conversations. Results stream in stages; failures retain validated partial results, and reconnect can replay the retained run.

7. **Performance work — implemented versus prospective.** Existing retrieval uses PostgreSQL full-text search and bounded graph/evidence selection. Pooling, proof deduplication and evidence-packing improvements are implemented. This WIP batches source-validation reads while retaining a consistent source snapshot. BM25/vector/HNSW hybrid search, optimized team selection and a replacement graph database remain proposals, not shipped capabilities.

The product purpose is to help someone move from “what am I trying to achieve?” to a small, inspectable set of relevant people, supporting evidence, missing information and next actions. It cannot infer undocumented offline relationships, a contact's full external network, willingness or decision-making authority.

## 3. Preview the new work without changing the running installation

Use a **fresh checkout**, preserving the current installation and its state:

```sh
git clone --branch codex/ironman-pause-handover --single-branch \
  https://github.com/markghiasy/sales-marketing-holistic-platform.git \
  ironman-handover
cd ironman-handover
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m scripts.network_demo --port 5055
```

Open `http://127.0.0.1:5055/inbox`, `/network` or `/strategy` on the same computer. This is the synthetic-data demo; a localhost URL on Eva's computer is not accessible from your Mac. Choose a free port if 5055 is occupied.

For an intentional Claude-backed synthetic question, stop that process and restart with an absolute path to your own existing configuration:

```sh
.venv/bin/python -m scripts.network_demo --port 5055 \
  --env-file /absolute/path/to/your/existing/ironman/.env
```

A submitted strategy question uses the configured commercial API and incurs provider usage. Credentials remain server-side. The project declares `anthropic>=0.125,<1`; handover checks used 0.125.0.

For **your real existing data**, follow [the separate Network trial upgrade guide](../demos/network-trial-upgrade.md). It covers source audit, the separate derived `network` schema, the app/worker, readiness checks and stopping the trial. Do not replay source migrations for the Network trial. Mac acceptance remains outstanding.

For **PR 5**, use [its identity-upgrade instructions at the pinned revision](https://github.com/markghiasy/sales-marketing-holistic-platform/blob/6543a8814670687229b8e31deae1c71d28068bf1/docs/delivery/2026-09-30-mark-identity-upgrade.md). Reconcile your existing patches and applied migrations before changing that installation.

## 4. Validation and known limits

**Current handover verification:** see [the verification record](2026-10-12-handover-verification.txt). It separates this run's results from older validation.

**Historical records:** PR 4 recorded 579 local passing tests; PR 5 recorded 399. These are the corresponding historical test runs, not a fresh full-suite or Mac result for this branch.

- **Refresh health remains unresolved.** The latest retained real-data inspection on 5 October ended with graph version 9 stale and the worker reporting `source_unavailable`, following connection/advisory-lock investigation. A readable old graph was not proof of successful refresh. This handover does not claim recovery or a fresh live-health check.
- **Latency remains material.** The last retained real-data strategy answer took approximately 77 seconds. Component speedups do not establish a faster end-to-end answer.
- **Progressive output has a bounded demonstration.** One 5 October synthetic live-provider run showed its first subgraph at 7.91 seconds and completed at 57.58 seconds. It retained partial assessments and omitted an unsupported proposal. It is not a production latency or reliability guarantee.
- **Strategy runs are process-local.** Up to eight runs are retained for 30 minutes; restart loses them. A run has a 180-second budget. Cancellation prevents subsequent work but cannot forcibly stop an already-running synchronous request.
- **Evidence quality is still a review concern.** Schema/quotation/source-binding checks improve traceability; they do not prove that an observation supports a proposed role or that a person is suitable for the goal.
- **Real-data acceptance is outstanding.** Database integration checks, source semantics, storage quota, continuous refresh and the target Mac must be verified before broader use. Tests must use a disposable test database.
- **No automatic external action.** The current Strategy work recommends conditional next steps. It does not send outreach, schedule meetings or execute tasks on the user's behalf.

## 5. Unipile: retained research, no adoption claim

The own-account trial demonstrated sample message/history retrieval, an email attachment check and one observed live webhook event per channel. A separate bounded three-contact LinkedIn pilot returned profile information. Those profiles were not written into the production graph. The temporary webhook experiment was cleaned up; it was not a persistent ingestion connector.

Your per-channel decision remains the reference point: keep direct Microsoft Graph for Outlook; hold LinkedIn; evaluate WhatsApp only as a possible purchase. The requested WhatsApp head-to-head against your 3,153-message window, predeclared acceptance gates and written vendor answers on history, residency/DPA and profile processing are **not established as complete** in this handover. The earlier sample trial does not satisfy those gates. Under your stated 7 October deadline, there is no evidenced go decision.

Research reports are dated observations, not current pricing quotes, a vendor security audit or a ban-free guarantee:
- [Pricing and fit](../research/2026-09-30-unipile-pricing-and-fit.md)
- [Trial observations](../research/2026-10-02-unipile-live-trial-assessment.md)
- [Security and platform risk](../research/2026-10-02-unipile-security-and-platform-risk.md)
- [Profile pilot and source-refresh status](../research/2026-10-05-unipile-profile-pilot-and-search-status.md)

## 6. Where to pick up later

If the project resumes, the first steps are to agree one concrete strategy use case, reconcile the identity and Network branches, restore and verify source-to-graph refresh, and repeat acceptance on the target machine. Then measure first useful evidence, total latency, answer support and API cost on fixed scenarios before choosing the next search change.

The project tickets have been backfilled in [Linear](https://linear.app/mlai-aus/project/studio-project-ironman-2f1a6ddc9f72), with completed, in-review, in-progress and backlog work separated.

The new commit contains product source, tests and engineering records. New personal academic drafts, credentials, real-message/profile payloads, local runtime state and virtual environments are excluded. Existing private data stays with its current operator. No production migration, deployment, new ingestion run or vendor purchase was performed as part of preparing this bookmark.
