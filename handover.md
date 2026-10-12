# Ironman — project summary and handover
**Prepared by Eva Ng · 12 October 2026 · Project paused**

This document summarizes the whole delivery, from the ingestion foundation to the current Network and Strategy trial. It maps the work to the original plan, identifies later changes, and separates implemented software from measured quality and operational acceptance.

**Delivered:** a three-channel ingestion and relationship store; identity review and reversible merges; a real-data Inbox with generated briefs and operational tools; and a separate evidence-backed Network/Strategy trial. **Not delivered as a complete workflow:** commitment-to-task management, Notion synchronization, daily digest/delegation, personal-voice outreach drafting and its approval/feedback pipeline. The original end-to-end MVP is therefore incomplete.

The latest handover runtime is `a765ab995897c87ecce8307fd6ae45ab38ac7e2a`. Its [GitHub CI](https://github.com/markghiasy/sales-marketing-holistic-platform/actions/runs/38206178002) passed **663 tests**, including PostgreSQL and browser tests, with lint/syntax checks also passing. This establishes software regression coverage, not acceptance by Mark, identity precision or production readiness.

## 1. The original product and what changed

The baseline is **Comms & Outreach Platform — MVP 1.0 Build Plan, v3.0, 12 August 2026**, supplied by Mark. Its central design was one portable relationship store supporting two outcomes:

- A consolidated inbox that turns commitments into manageable work.
- A network that supports partner selection and human-approved outreach.

Vendor-specific adapters normalize through an Envelope into PostgreSQL. The downstream task and outreach products consume that store. Sending remains a human action.

Development first established ingestion, identity handling, the Inbox and operating procedures. Later work expanded the original SQL relationship views into an evidence-backed graph explorer, reviewed profiles and goal-driven Strategy workspace. Identity policy also changed toward provisional suggestions instead of heuristic automatic fusion. Those additions are useful work in their own right; they do not fulfill the unbuilt task and outreach stages by substitution.

This summary uses the original plan's block boundaries. The **31 August Block A record** (retained locally) includes some three-channel work that the original plan placed in Block B. Its dated implementation evidence remains useful, but its scope wording should not redefine the original milestones.

## 2. Overall completion against the original checkpoints

“Implemented” means executable code exists with identified evidence. “Accepted by Mark” requires a separate acceptance record. An open PR, passing test or positive demo reaction is not that record.

| Original block | Expected outcome | Evidence-backed position at pause |
| --- | --- | --- |
| **A — foundation** | Outlook full/incremental sync, rerun without duplication, restorable export, deploy/configuration, CI and runbook | Substantial implementation and historical clean-deploy/export evidence exist. The Block A sign-off checkboxes remain empty. Portability/governance exceptions below prevent treating this as a fresh unconditional certification. |
| **B — channels and relationship foundation** | WhatsApp/LinkedIn, identity resolution, deterministic/relational noise handling, SQL graph; a correct consolidated timeline and credible relationship ranking | Mechanisms implemented and used with real data. Identity quality required remediation; completeness varies by source. No complete recorded acceptance of the three-channel timeline and ranking checkpoint was found. |
| **C — useful triage inbox** | Real inbox, semantic triage, scored identity review; useful enough to replace the normal inbox for a day | Inbox, briefs and review UI implemented. Brief generation is not the complete semantic-classifier/feedback workflow specified in the plan. No recorded one-day acceptance trial was found. |
| **D — commitments become tasks** | Thread-level extraction, deduplication, Notion source links/read-back, digest, delegation | No delivered execution workflow found. An `action` table is a schema provision, not a working task product. |
| **E — complete outreach workflow** | Criteria scoring, voice retrieval, drafts, approval/edit feedback; one continuous live walkthrough | No delivered complete workflow found. Strategy candidate selection is not the specified persisted outreach pipeline. |
| **Cutover** | Clean deployment, Mark's self-deployment and authentication, operational handover and original-instance teardown | Historical clean-install evidence and deployment guidance exist. The current Network trial still requires target-Mac acceptance; no complete written teardown/revocation record was found. |
| **F — tuning on Mark’s data** | Mark’s criteria and voice, volume shakeout, twenty explained prospects and sendable drafts | No recorded completed acceptance. Requires the missing D/E capabilities and evaluation on Mark’s data. |

**How much is done?** The defensible answer is “a substantial foundation across A–C, plus an additional Network/Strategy trial; D–E and the final F walkthrough are not delivered.” A single percentage would mix unequal blocks, later scope and different levels of verification. No formal completion percentage or full MVP sign-off is claimed.

## 3. What was built, why it matters, and its limits

Location labels: **Core** = established source/Inbox stack; **Identity PR** = separate PR 5; **Network** = PR 4 and this handover branch.

| # | Capability and requirement source | Delivery and practical value | Boundary / evidence |
| --- | --- | --- | --- |
| 01 | **Shared Envelope and store** — original §§4–7 | Core. Stable channel/message/thread/identity structure and common writer; display names and To/Cc roles added. Makes channel replacement and downstream consumers possible without rewriting every feature. | [Envelope](adapters/envelope.py), [writer](adapters/store_writer.py), [schema](db/migrations/0001_init.sql). A clean interface does not prove an alternative provider preserves every field. |
| 02 | **Outlook ingestion** — §§6,14 | Core. Backfill, incremental delta, refresh/retry handling, body cleanup and stable message deduplication. | [Adapter](adapters/outlook/sync.py), [runbook](runbook.md). Default Inbox/Sent coverage can omit filed mail; all-folder improvement is in PR 5. |
| 03 | **WhatsApp ingestion** — Block B | Core. Linked-device collector, queue-to-Envelope ingestion, identity normalization, encrypted session state and liveness monitoring. | [Adapter](adapters/whatsapp/sync.py). Persistent process and protocol maintenance remain necessary. Group exclusion occurs at queue drain, not before collection. |
| 04 | **LinkedIn messages and connections** — Block B, §8 | Core. Official export import plus a paced session-based message collector, session cap, connection/company/title data. | [Export adapter](adapters/linkedin/export_sync.py), [session limits](adapters/linkedin/session_limit.py). Connection snapshots are not a contact's full career/skills history or second-degree network. Off-machine reliability and platform risk remain limits. |
| 05 | **Cross-channel identity and review** — §8 | Core. Deterministic matching, scored suggestions, confirm/reject queue, structured organizations/facts and human linking. | [Resolution code](adapters/resolution/run.py), [review UI](scripts/onboarding/templates/resolution.html). Low population overlap limits matching recall; passing code tests cannot establish identity precision. |
| 06 | **Reversible and attributable merges** — §7; later quality requirements | Core. Soft merges, audit/undo and rule/decision-path attribution; explicit unknown provenance for legacy rows. | [Merge implementation](adapters/resolution/merge.py), [0010](db/migrations/0010_merge_provenance.sql), [remediation](docs/quality/2026-09-28-remediation.md). A correct observed merge is not sufficient statistical validation. |
| 07 | **Conservative identity suggestions** — later policy revision | Identity PR. Only exact-email remains automatic-merge eligible; heuristic suggestions carry evidence. Query-time statistics may aggregate eligible components without merging people. | [PR 5](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/5). Components capped at 8 identities and minimum 50% density; rejected paths prevent aggregation. Not included in this Network branch. |
| 08 | **Noise handling and relational signals** — §9 tiers 1–2 | Core. Header/sender/domain rules, persisted automation flag, sent/received/recency/reciprocity signals. Reduces deterministic noise before model work. | [Specification](openspec/specs/noise-parser-tier-1-2/spec.md), [reply signals](adapters/reply_signal.py). Human-value judgments and ranking quality remain separate questions. |
| 09 | **Real-data Inbox** — Block C | Core. Cross-channel conversation display, channel/unread/unanswered filters, local read state, contact editing/linking, hide/unhide, generated context and live updates. | [Inbox routes](scripts/onboarding/app.py), [query layer](adapters/inbox_query.py). Local read state is not mailbox read-state synchronization. Draft-reply UI is explicitly a placeholder. |
| 10 | **Brief generation and failure visibility** — Block C; later quality requirements | Core. Precomputed summaries/context/topic/urgency, post-sync refresh, strict output, exact token preflight, bounded input and durable failure/partial-history status. | [Brief generation](adapters/ai_brief.py), [0011](db/migrations/0011_ai_brief_status.sql). These are generation/reliability controls, not a measured guarantee that summaries or implied relationships are correct. |
| 11 | **Freshness across provisional identities** — later identity review | Identity PR. Dependency revisions, stale-brief withholding, affected-contact refresh and bounded regeneration command. Avoids presenting stale context as current. | [PR 5 delivery](https://github.com/markghiasy/sales-marketing-holistic-platform/blob/6543a8814670687229b8e31deae1c71d28068bf1/docs/delivery/2026-09-30-mark-identity-upgrade.md). Topology invalidation is conservative and can trigger extra regeneration. |
| 12 | **SQL relationship foundation** — §10 | Core. Contact statistics, reciprocity, last message and provisional graph-strength ranking over the existing store. | [SQL views](db/migrations/0002_graph_views.sql). Ranking weights are explicitly uncalibrated; context is exposed separately, not a validated fourth scoring term. |
| 13 | **Full graph and conversation slices** — expanded Network requirements | Network. Shared light-theme renderer, sidebar access, embedded contact slice, multi-label display, filtering, source inspection and preserved navigation context. | [Product catalogue](docs/artifacts/network-product-review-for-mark.md), [explorer guide](docs/demos/network-explorer.md). Rendering polish is not evidence of business effectiveness. |
| 14 | **Four relationship scopes and time** — expanded exploration requirements | Network. Direct interaction, documented collaboration/introduction, shared project/team context and shared organization/company context; current/historical queries. | [Scope design](docs/superpowers/specs/2026-09-28-relationship-scopes.md). Overlapping evidence categories, not four levels of friendship. A separate team-roster importer is not implemented. |
| 15 | **Reviewed profiles and contextual views** — expanded business questions | Network. Person/organization/project context, evidence-backed profile proposals, confirm/reject history and source invalidation. | [Profile design](docs/superpowers/specs/2026-09-28-strategic-profile-demo.md), [real trial](docs/demos/2026-10-02-real-network-validation.md). Project views summarize available evidence; they are not task assignment, verified delivery tracking or a full project-management system. |
| 16 | **Search and bounded evidence retrieval** — Network discovery/performance requirements | Network. Deterministic contact search, PostgreSQL full-text retrieval, typed graph paths, bounded evidence packs and source checks. Pooling, proof deduplication and packing/read batching reduce specific costs. | [Retrieval](docs/demos/network-retrieval.md), [measurements](docs/demos/2026-10-02-real-network-validation.md). BM25/vector/HNSW hybrid search and a new adaptive research algorithm are not shipped production capabilities. |
| 17 | **Goal-driven Strategy workspace** — expanded strategic-use requirements | Network. Goal requirements, up to three concurrent read-only retrieval workers, coverage assessment, one bounded gap-search round, conditional options and evidence-linked next actions. Progressive results survive a failed stage where valid. | [Validation record](docs/research/2026-10-05-strategy-workspace-validation.md). Not an autonomous task executor. In-memory runs expire or disappear on restart; citation checks do not prove capability, willingness or authority. |
| 18 | **Real-source graph lifecycle** — local trial requirement | Network. Read-only source boundary, separate derived schema, source binding, restricted writer, atomic publication, incremental/reconciliation worker, persistent reviews and freshness diagnostics. | [Upgrade guide](docs/demos/network-trial-upgrade.md). Continuous refresh is not operationally accepted: the last retained live inspection reported stale state and worker failure. |
| 19 | **Operations and portable delivery** — §§5,13–14 | Core/Network. Export, health checks, onboarding, deployment skills, migration/runbooks, isolated test databases and retained CI reports. | [Runbook](runbook.md), [deployment skill](.claude/skills/deploy-comms-platform/SKILL.md). Historical checks do not certify every target or today's running processes. |
| 20 | **Build-versus-buy investigation** — later channel decision | Research. Provider capability, pricing, security/platform-risk, sample history/attachment/webhook and bounded profile tests were documented. | [Unipile research](docs/research/2026-10-02-unipile-buy-versus-build.md). A trial is not a replacement ingestion deployment, security certification or accepted purchase. |

These twenty rows are an inventory, not twenty equally weighted contractual milestones.

## 4. Evaluation: what evidence supports which claim?

There are four separate questions:

1. **Does the implementation run correctly?** Unit, database and browser regressions; fresh installation and source-boundary checks.
2. **Are its identity judgments accurate and judgeable?** Blind, representative real-data grading with explicit unknowns.
3. **Does it remain healthy on the target system?** Folder coverage, refresh/reconnect, restart, latency, quota and target-machine acceptance.
4. **Does it improve the user's work?** Accepted use cases, ranking usefulness, quality of recommendations and eventual task/outreach outcomes.

### Identity quality and the response to evaluation

The [resolution release policy](docs/quality/resolution-release-policy.md) separates a **review-queue Wilson 95% lower bound of 0.70 with at least 100 scored pairs** from a **changed-rule automatic-merge bound of 0.99 with at least 400 scored pairs**. Unknown pairs are reported separately. Samples, blinding and preregistration matter; a filtered old sample is not a fresh holdout. The repository checker is an explicit release tool, not an automatically enforced CI/runtime gate.

The implementation response spans two deliveries:

| Evaluation concern | Response | Delivery / remaining check |
| --- | --- | --- |
| Name-only LinkedIn candidates lack independent evidence | Rule retired; pending items selectively withdrawn with history retained | Merged [PR 2](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/2), migration 0012. Replacement-quality acceptance is a separate measurement. |
| Merge audit cannot identify what caused a fusion | Required method and automatic/review/manual attribution; explicit legacy marker | PR 2, migration 0010. Auditability supports future measurement; it does not itself establish precision. |
| Oversized or malformed brief output fails invisibly | Strict output, token preflight, bounded truncation and durable status | PR 2, migration 0011; SDK compatibility in [PR 3](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/3). |
| Local versus CI database behavior is untrustworthy | Explicit disposable loopback DB, isolated schemas, failure on migration errors, executed-test checks | Merged. Latest handover CI ran 663 tests with no skips. |
| Heuristic identity fusion and fragment statistics | Suggestion-first policy, bounded provisional aggregation, evidence UI and freshness dependencies | PR 5, not integrated into this branch. |
| Filed mail is missed; signature-phone attribution is unsafe; upgrades generate unexplained suggestions | All-folder opt-in with exclusions/checkpoints, signature-phone retirement, run/rule/code provenance | PR 5, migrations 0013–0015; target-instance acceptance remains distinct from code completion. |

Mark supplied additional private evaluation and follow-up messages. Their detailed findings are summarized in the **separate local evaluation and acceptance appendix**, not newly reproduced in this public repository. No fresh whole-queue quality pass or complete closure of Mark’s entire findings register is established here.

### Current regression evidence and performance limits

- **Current handover runtime:** 663 tests passed in 116.41 seconds in GitHub CI, including real disposable PostgreSQL and headless browser interaction. Integration execution checks also passed.
- **Separate identity upgrade:** its [validation record](https://github.com/markghiasy/sales-marketing-holistic-platform/blob/6543a8814670687229b8e31deae1c71d28068bf1/docs/delivery/2026-09-30-identity-validation.md) records 399 local tests and a passing historical CI run. These tests are not part of the current handover branch's claim.
- **Real Network trial:** the dated acceptance record contains source-backed UI/citation checks and a roughly 77-second strategy response. This remains a material latency limit.
- **Synthetic progressive Strategy:** one recorded live-model run produced a first subgraph at 7.91 seconds and completed a partial assessment at 57.58 seconds. Different data and different work: this is not a controlled improvement over the real-data result.
- **Freshness:** the [5 October operational record](docs/research/2026-10-05-unipile-profile-pilot-and-search-status.md) ends with stale graph state and `source_unavailable`. Current CI success does not demonstrate that the live worker recovered.

## 5. Architecture retained for the next operator

```text
Outlook / WhatsApp / LinkedIn
           |
    channel adapters
           |
        Envelope
           |
 PostgreSQL source store
   |       |          |
 identity  Inbox      read-only source adapter
 review    + briefs          |
   |                    derived network schema
   |                  + persistent human reviews
   |                         |
   +-- PR 5 improvements     graph / search / Strategy
       remain separate       |
                        evidence + conditional actions
```

The source store remains the durable integration boundary. The Network trial introduces derived state within PostgreSQL, rather than replacing the source with a separate graph-database service. This makes source validation, provenance and retraction explicit, at the cost of derived storage and refresh complexity.

Potential identity equivalence and professional relationships are different concepts. A “may also be” edge must not become a collaboration edge. Likewise, an LLM's query-specific candidate connection belongs to the opportunity map, not automatically to the factual graph.

A task/execution layer would be a future consumer. The current application does not complete it by generating an action recommendation.

## 6. Ground rules and portability: controls and open items

| Requirement area | Evidence / limitation |
| --- | --- |
| Human sends | No delivered autonomous outreach/sending workflow. Inbox draft placeholders and Strategy suggestions must not be presented as working delivery agents. |
| Read-only source access | Network source transactions and derived-writer privileges are regression-tested. Application behavior is not a claim that unofficial messaging protocols offer Microsoft-style read-only OAuth enforcement. |
| Credentials/configuration | Runtime credentials are external configuration. An existing Microsoft public client ID remains a source constant in `adapters/outlook/client.py`; it is not a secret, but it is an exception to the original “every app ID is configurable” wording. |
| LinkedIn pacing | Local session limits and schedules exist. They reduce configured activity, not guarantee account safety or give control over a third-party provider's internal traffic. |
| Data custody and access | Deployment separation is documented. Current hosting, access revocation, token custody and any final data-deletion sign-off were not independently re-certified in this audit. The August custody blocker is historical, not proof of today's hosting state. |
| Export and reproducibility | Historical complete dump/restore and clean deploy checks exist; Network trial requires the complete source checkout, including assets and SQL. Target-Mac acceptance remains pending. |
| Retention | WhatsApp group records are discarded when draining the local queue; exclusion before initial collection remains an identified gap. |
| Model governance | Commercial-provider integration and request bounds exist. Contractual data-processing/residency assurances and semantic-output quality need their own evidence. No compliance certification is claimed. |

No production source, credential, migration, collector or paid backfill was changed to prepare this handover.

## 7. Code map and how to inspect it

| Delivery | Reference | Status |
| --- | --- | --- |
| Quality fixes and tested SDK range | PR 2 / PR 3; merged revision `1337533` | Merged |
| Persistent Network trial | [PR 4](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/4), head `50ce177` | Open draft |
| Suggestion-first identity / filed Outlook mail | [PR 5](https://github.com/markghiasy/sales-marketing-holistic-platform/pull/5), head `6543a88` | Open; separate |
| Progressive Strategy and handover | `codex/ironman-pause-handover`, runtime `a765ab9` | Published, CI passing; contains PR 4 ancestry, not PR 5 |

Use the [version-specific pause bookmark](docs/delivery/2026-10-12-pause-bookmark.md) for synthetic preview commands and a compact snapshot of the additional work. Use the [real Network upgrade guide](docs/demos/network-trial-upgrade.md) for a separate real-data trial, and PR 5's pinned instructions for its separate migrations.

Do not apply all historical source migrations to an existing installation, or assume one branch contains the other. The documentation-only summary does not change that release topology.

## 8. What remains if work resumes

1. Reconcile the identity and Network deliveries and choose a named release; preserve local patches and migration history.
2. Restore and verify continuous source-to-graph refresh on the target system, including restart/reconnect and truthful freshness reporting.
3. Complete target-machine and representative identity-quality acceptance with declared criteria.
4. Agree one concrete strategic workflow and measure useful evidence, unsupported claims, first-result/total latency and cost.
5. Decide the channel-provider question against the documented gates; sample provider experiments are not sufficient adoption evidence.
6. Only then scope the unbuilt task or outreach stage explicitly. Its implementation and evaluation remain future work.

This list is a resumption order, not authorization to restart the paused project.

## 9. Evidence guide and provenance

- **Original build plan:** v3.0, 12 August 2026, §§1–14; reviewed locally. The original PDF is not newly published here.
- **Foundation:** the dated Block A record (retained locally), [runbook](runbook.md), source migrations and adapter tests.
- **Inbox/identity:** [Inbox design](docs/superpowers/specs/2026-09-16-triage-inbox-real-data-llm-design.md), [remediation](docs/quality/2026-09-28-remediation.md), [release policy](docs/quality/resolution-release-policy.md), PR 5 records.
- **Network product reasoning:** [numbered product catalogue](docs/artifacts/network-product-review-for-mark.md). It is a dated synthetic-demo record; later real-data work is documented separately.
- **Real trial and current increment:** [acceptance record](docs/demos/2026-10-02-real-network-validation.md), [Strategy validation](docs/research/2026-10-05-strategy-workspace-validation.md), [current passing CI](https://github.com/markghiasy/sales-marketing-holistic-platform/actions/runs/38206178002).
- **Private evaluation evidence:** downloaded 28 September quality specification, 30 September patch file, and Mark’s messages supplied by Eva. See the local appendix for their interpretation and limitations.

The earlier externally hosted “Identity Resolution Status” artifact and the complete findings register were not recovered in this audit. Conclusions rely on the accessible records above. No claim is made that every historical finding is closed. Personal academic work and later personal multi-agent concepts are outside this delivery assessment.
