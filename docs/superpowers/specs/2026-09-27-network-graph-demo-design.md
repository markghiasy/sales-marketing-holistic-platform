# Network graph demo — proposed design

Date: 2026-09-27. Revised after the architecture comparison, Eva's request for a demo for Mark and a paper for her supervisor, and her screenshot clarifying that a full network must supply embedded contact slices. Status: DESIGN CONFIRMED by Eva's “对，现在干啥” after the revised written spec was presented. Implementation-plan review and execution-method selection remain next.

## Delivery brief

Two linked deliverables use the same scenarios and evidence model:

1. An English interactive demo and a five-minute presenter script for Mark, with both a full Network explorer and a contact-centered slice embedded in the existing Inbox detail layout. Success means a viewer can find a relevant contact, inspect supported relationships and evidence, see temporal changes, and move between the two views without contradictory data or lost context.
2. An English supervisor-facing design/prototype paper, targeting 6–8 pages excluding references unless a required template or deadline changes that assumption. Deliver editable source plus a rendered PDF. Success means a reader can identify the research question, prior systems, proposed contribution, implemented scope, evaluation method, actual results and limitations without confusing them.

No delivery date has been supplied. Mark's actual business questions and the supervisor's required format remain inputs, not reasons to delay preparing the specification. First use explicitly fictional commercial scenarios; their mechanical correctness is not evidence of industrial usefulness. No private correspondence is included in the paper or shareable demo.

Recommended delivery order: build the reproducible synthetic demo and draft the paper's introduction/related work/design; then run the demo's checks and a separately isolated Graphiti feasibility probe; finally add measured findings, limitations, screenshots and the presentation script. A Graphiti integration is conditional on the probe, not a prerequisite for showing the deterministic demo.

Alternative routes considered: a Graphiti-first demo offers earlier backend realism but couples the presentation to extraction and infrastructure uncertainty; a live-data-first demo offers stronger business relevance but requires selected representative cases and a separately scoped data integration. The synthetic-first route gives both audiences a concrete artifact and a reproducible baseline.

## Intended outcome

Demonstrate to Mark how the product can answer three questions:

1. Who in my network matches a function, organization, or project?
2. How do I know this person, and what evidence supports each relationship?
3. Why is this person relevant now, even if our long-term relationship is different?

The network owner (ego) is explicit and distinct from the currently focused contact. Focusing Mark in Eva's network does not change the owner to Mark. The owner stays available in the view header; show the ego node when supported connecting evidence exists, and never invent an edge to keep the view connected. This is a product/architecture demonstration, with explicitly labeled synthetic data, before a separately verified real-data integration. English UI; discussion with Eva in Chinese.

## Frontend verification and revised product shape

Eva supplied a screenshot of the existing Inbox detail panel: messages on the left, context and a sparse Network visualization on the right. Source inspection confirms `scripts/onboarding/templates/inbox.html` renders `renderGraph(c.name, c.graph)` in that slot. It uses a fixed 620-by-380 SVG viewBox, radial positions, full relationship sentences as edge labels, and name-based navigation through `personKeyForName`. `adapters/ai_brief.py` defines graph data as one optional organization and a list of people containing name/relation strings. The detail JSON endpoint returns that cached graph unchanged. This verifies screenshot/source correspondence, not a live-browser interaction test.

Consequences: the current visual is a per-contact summary diagram, not a slice queried from a canonical cross-contact graph. Long labels compete with nodes, available space is poorly used for sparse cases, and the graph payload has no canonical entity IDs, explicit claim evidence IDs or temporal intervals. A visual restyle alone does not deliver the requested full-network/slice relationship.

Required product structure:

- **Full explorer:** a dedicated Network view with search, person/organization/project filters, pan/zoom, fit-to-view, selective neighbor expansion, a ranked people list and an evidence inspector. The bounded viewport remains in force; a full-network entry point does not mean rendering every node simultaneously.
- **Embedded slice:** a compact view in the existing Inbox Network slot, focused on the selected contact and a bounded relevant neighborhood. Default to at most 8 nodes and 12 edges, with omitted counts and an Open full network action. Use short relationship labels; full explanations, provenance and time information belong in the inspector. Isolated contacts get a useful evidence-limited state, not decorative unsupported edges.
- **Shared implementation:** one reusable graph renderer with compact/explorer modes and one graph-query contract. Keep graph rendering separate from snapshot selection and host-page navigation. The embedded view is an interactive component, not a screenshot of the explorer or a separately generated AI graph.
- **Shared state:** carry focused entity ID, filters, observation time and selected claim when opening the explorer; returning restores the contact panel. Distinguish inspecting a person from opening that person's conversation. Never resolve a graph click solely by display name.
- **Demo integration:** show both views on fixtures. The Inbox preview reuses the existing detail template and mounts the shared component in its Network slot under explicit demo configuration; it must not mix synthetic graph nodes with private real messages. Production activation and real-data integration remain separate changes.

Visual requirements: readable labels at the actual embedded width, no overlap obscuring selected nodes, person/organization/project distinctions beyond color alone, clear focus and selected-edge states, stable layout during selection, and meaningful use of space for both two-node and dense slices. Preserve the existing messages/context layout. Browser validation must cover the actual embedded slot and full explorer, not just a standalone graph screenshot.

## Architecture options

| Option | Benefit | Limitation | Recommendation |
|---|---|---|---|
| Typed graph projection over the existing Postgres model | Reuses ingestion, provenance, identity resolution, and deployment | Requires implementing temporal extraction/retrieval if those are needed | Deterministic demo and evaluation baseline; production engine undecided |
| Extend each contact's `ai_brief.graph` JSON | Small initial UI change | Fragmented identities, no cross-network consistency, overwritten history, weak evidence | Insufficient as the canonical graph |
| Graphiti temporal graph behind an adapter | Reuses existing temporal extraction and hybrid retrieval | Adds graph storage, model dependencies and identity consistency work | First engine to probe against the baseline, before production adoption |

The first demo runs in an isolated Flask app with fixtures and the same graph response contract intended for a later Postgres projection. It does not need a database migration or a model call.

Backend provenance is visible: the first deliverable is a deterministic scenario backend. It must not carry a Graphiti-powered claim unless that backend is actually connected and exercised. Hindsight remains an alternative if agent-memory retrieval becomes the primary requirement; running both engines is outside this scope.

## Scope of the first demo

- One ego, approximately 24 fictional contacts, three organizations, and two projects.
- People can have multiple functions and multiple relationships.
- Overview with graph, ranked people list, and an evidence inspector.
- The same graph component embedded in a fixture-backed preview of the existing Inbox detail panel, with a context-preserving transition to the full explorer.
- Search names plus explicit Function / Organization / Project filters.
- A person remains selectable from the list as well as the graph; keyboard-accessible controls and textual evidence are required.
- Switch between Current relevance and Relationship history; show both measures in detail.
- Time control replays a predefined scenario. A “New reply” action adds a synthetic event, then the visible graph/ranking updates through SSE.
- A “Reset scenario” action restores fixtures. No write goes to the existing application's database.
- Every screen carries a Synthetic demo label. Evidence text is fictional and labeled accordingly.

## Deliberate exclusions

- No live LLM extraction, no production data backfill, no outbound messages.
- No complete natural-language assistant or automatic project discovery from topic similarity.
- No inferred trust/personality score, Slack integration, Team entity, or social Event entity.
- No million-node performance claim. A bounded viewport is a UX choice; it is not a database scaling benchmark.
- No copy of third-party scoring code or UI assets.

## Source, claims, and graph projection

Use separate conceptual layers even when fixture data is small:

```text
source episodes + identity bindings + reviewed claims
                         |
              deterministic graph projection
                         |
             bounded graph response + evidence
                         |
          UI graph / people list / inspector
```

Node types: `person`, `organization`, `project`; ego is a person with an explicit role. Node IDs are opaque typed IDs, never display names. Fixture IDs are stable across scenario changes.

Edge kinds include `communicates_with`, `works_at`, `member_of_project`, `client_of`, `collaborates_with`, and evidence-supported `introduced_by`. Several different edges may join the same pair.

Each claim carries:

- ID, subject, predicate, typed object;
- scope (`world` or `ego_relative`, with an explicit ego ID for the latter);
- review status (`pending`, `confirmed`, `rejected`);
- origin (`structured`, `manual`, `model`);
- supporting source IDs and a quoted excerpt available in the inspector;
- observed timestamp; optional validity interval with unknown dates left unknown.

Pending claims are visible only when the user turns on a separate hypotheses layer. The UI must not silently treat them as confirmed edges. Confidence is a model assessment, not the truth probability of a social claim.

Production mapping: existing `identity`/`person`, `organization`, `fact`, `message`, and `message_participant` remain useful. Project membership and temporal provenance need explicit additions. Source claims should retain identity anchors so graph grouping can be recomputed after merge or undo; browser IDs require an alias/version strategy for stale references.

## Scoring behavior to validate

The demonstration distinguishes observable history from current activation. Coefficients are adjustable engineering defaults, with a visible explanation, not research-validated measures of friendship.

Only eligible direct human exchanges affect familiarity. One-way contacts remain discoverable but are labeled “No observed two-way exchange”; they cannot gain a strong relationship just by sending many messages. Missing channel coverage is shown as unknown, not as proof of a weak relationship.

Preprocessing must deduplicate messages per resolved contact, use participant roles to attribute authorship, and separate CC/group participation and automated mail. Collapse message bursts into conversation sessions before scoring. A proposed demo rule groups direct messages within the same contact/channel when adjacent messages are no more than 30 minutes apart; one session can contain both inbound and outbound evidence. This parameter is explicitly provisional.

For session age in days `a >= 0` and configurable half-life `h > 0`:

```text
decay(a, h) = exp(-ln(2) * a / h)
activity(h, t) = sum(decay(t - session.timestamp, h))
normalized_activity = 1 - exp(-activity / saturation_scale)
```

Half-life means one isolated contribution halves after `h` days. Future events are excluded from a historical query. Defaults for the demo: fast half-life 30 days, slow half-life 180 days, saturation scale 4 sessions. Reject nonpositive half-lives/scales.

Show fast activity as current temporal relevance. Show slow activity alongside reciprocal session ratio, number of active days, relationship duration, and channel breadth as relationship-history evidence. Do not collapse those into a supposedly objective trust score. A newly urgent project may raise contextual relevance without claiming an established strong bond.

Search/filter relevance is applied before temporal ranking. Matching project membership is a separate relevance reason. The first demo does not invent a universal weighted sum of project relevance, urgency, and closeness. Ties have a deterministic ID ordering; the inspector states which rule ranked the person.

This deliberately tests whether two understandable views are more useful than the old single `graph_strength` formula. Final production coefficients and personalized decay behavior remain a calibration decision.

## Query and update contract

Proposed endpoints for the isolated demo:

- `GET /network` — graph UI.
- `GET /network/graph.json` — typed nodes, edges, ranked contacts, counts, evidence references, snapshot version, computed time, and truncation flag.
- Both hosts use this endpoint with a stable `focus` entity ID and a `view` of `compact` or `explorer`, plus identical filter/time semantics. Compact results must be a bounded selection of the same underlying eligible graph; changing display mode never changes a claim's truth status or identity.
- `GET /network/evidence/<id>.json` — fictional evidence for the selected edge.
- `GET /network/events` — SSE invalidation/version events and heartbeat.
- `POST /network/demo/reply` and `POST /network/demo/reset` — scenario-only mutations.

Server limits: at most 50 displayed nodes including ego/context and 100 edges; callers cannot override the hard maximum. Return omitted counts. Expand only explicitly selected context nodes, at most two hops. A shared organization is represented by membership edges through its organization node, not by every possible person-to-person pair.

A commit to scenario state advances its version; clients refetch a coherent snapshot after an SSE signal. On reconnect, fetch the latest snapshot even when no notification was received. Refresh the selected inspector as well as the list. Time controls recompute activation without needing new message events.

Production extension: invalidate after message ingest, completed brief/graph extraction, reviewed facts, identity merge/undo, and user corrections. A lightweight durable revision/outbox can make missed updates recoverable; LISTEN/NOTIFY can wake consumers but is not the durable record.

## Demonstration stories and acceptance checks

1. **Accountants:** function filter returns matching people, retains ego, and offers evidence for the classification.
2. **Shared context:** organization/project views show how people connect through that context; no unsupported reporting-line edge appears.
3. **Several roles:** one person is both client and collaborator, with separately inspectable claims.
4. **Old collaborator:** time advances and current activation drops while slow history remains comparatively substantial; the person is still searchable.
5. **New project contact:** project relevance surfaces someone with little direct history; UI states the reason and the limited familiarity evidence.
6. **Cold inbound:** many one-way messages do not turn an unreciprocated contact into a strong tie.
7. **Live change:** a simulated reply changes the graph/ranking without manual refresh; disconnect/reconnect converges to the latest version.
8. **Evidence ambiguity:** pending introduction remains visually distinct from a confirmed introduction; two identical display names remain distinct IDs.
9. **Time correctness:** no event after the selected time affects ranking; unknown fact validity is not invented.
10. **Scope honesty:** a missing-channel relationship is marked missing evidence; fixture claims are never presented as live extraction.
11. **One graph, two views:** the embedded Inbox slice and explorer agree on identities, selected claim, evidence, review status and temporal validity for the same snapshot. Open full network preserves focus/filter/time; return restores the originating contact.
12. **Visual usability:** two-node and dense slices have readable labels at the host panel's actual width. Expanding, selecting and inspecting do not unexpectedly reset zoom or obscure the selected item. Keyboard-accessible list and inspector offer equivalent access.

Implementation verification should target these behaviors, especially deduplication, role attribution, decay boundaries, evidence status, stable IDs, response bounds, and SSE recovery. Browser verification must exercise filters, selection, timeline and live updates on the actual rendered demo.

## Later real-data validation

A separate adapter may read a transaction-consistent snapshot from the configured store after explicit read-only transaction verification. It must not modify production state or expose raw messages through a public demo. Demonstrate only supported functions/organizations; unknown self membership and absent project evidence stay visible as gaps.

Before any live extraction, repair and verify the actual runtime dependencies and surface extraction failure/staleness independently from successful message sync. Applying migrations, enabling paid extraction, and deploying the graph are separate concrete changes.

## Five-minute presentation for Mark

1. **Start in Inbox, then explore:** open a fictional contact's conversation, inspect its embedded neighborhood and choose Open full network. Preserve the focus, then choose a fictional project needing an accountant with logistics experience and inspect the filtered shortlist. These are explicit fixtures, not claimed natural-language understanding.
2. **Reason to contact:** inspect the path through a shared project or a confirmed introduction; open the fictional message supporting each claim.
3. **History versus immediate relevance:** compare an established collaborator with a recently active contact. Switch views and inspect the different reasons for prominence.
4. **Changed circumstances:** replay an employer change, distinguishing when it became effective from when evidence arrived. Preserve simultaneous roles when evidence supports them; do not apply a last-message-wins rule. Historical snapshots use only evidence known by the selected observation time; the inspector separately displays fact-validity dates.
5. **New information:** simulate a reply, see the shortlist update, and reset the scenario. Finish with the business questions to validate on Mark's selected cases.

Identity ambiguity and merge/undo remain engineering checks; they need not occupy the main presentation. The script explicitly distinguishes implemented mechanics, proposed extraction, and future business validation.

## Paper design

Working title: **Evidence-Grounded Temporal Relationship Memory for Personal Business Assistants**. Position this as a system design and prototype study. Do not claim a novel temporal graph engine, biological fidelity, validated trust inference, or state-of-the-art performance.

Research question: can an ego-centric representation that separates reviewed temporal assertions, interaction history and task relevance support more correct and explainable contact retrieval than simpler memory representations?

Candidate contributions, to be supported rather than assumed:

- A representation joining canonical identities, source evidence, review status and temporal relationship assertions.
- Separate treatment of observed relationship history and current task relevance, with explicit handling of missing evidence.
- A shared evidence-backed graph exposed through task-focused contact slices and a broader explorer. This is a system interaction design to evaluate, not a standalone claim of algorithmic novelty.
- A reproducible scenario suite covering changed roles, simultaneous roles, identity ambiguity and evidence-backed contact selection.

Planned structure:

1. **Abstract and introduction:** the business retrieval problem; motivating failure of a static contact list or an ungrounded person summary.
2. **Related work:** Graphiti/Zep, Hindsight, GraphRAG, A-MEM and Generative Agents; compare temporal semantics, provenance, entity control and retrieval units. Cite TAPE only to the extent its primary evidence can be inspected.
3. **Requirements and model:** ego-relative versus world assertions; identity, episodes, person models, relationships, context and activation; map the original six conceptual layers to concrete responsibilities.
4. **Architecture and prototype:** authoritative store, replaceable graph projection/engine, retrieval policy, UI; state exactly which parts run on fixtures and which have real engine support.
5. **Evaluation:** scenarios, baselines, metrics, known-answer labels and reproducibility settings.
6. **Results and discussion:** only completed measurements; label unexecuted comparisons as planned evaluation. Separate correctness checks from usefulness judgments.
7. **Limitations and conclusion:** synthetic evidence, sample size, missing channels, extraction error, provisional decay parameters and lack of established industrial benefit.

Evaluation ladder:

- First compare deterministic baselines on the same fixtures: function/organization filtering; filtering with recency ordering; typed temporal relationships with evidence and task context. Measure expected contact inclusion, unsupported-edge count, historical/current fact correctness and evidence-link correctness. These support a prototype evaluation only.
- Add vector-only and Graphiti comparisons only when those paths actually run on the same inputs. Fix model/provider configuration and record ingest/query costs and latency; do not import another paper's benchmark numbers as our results.
- Reserve industrial validation for Mark's selected tasks with expected useful contacts and evidence. User feedback can assess usefulness and explanation clarity; no participant count or study result is invented.

The demo must export reproducible scenario outcomes so paper tables can be regenerated. A table row clearly identifies its backend and measured versus unexecuted status. The paper's original draft and supervisor expectations should guide terminology; do not list Mark or the supervisor as coauthors without agreement.

## Isolated Graphiti probe

Question: can Graphiti preserve our controlled identities and temporal assertions while returning useful, source-linked candidates at an acceptable integration cost?

Use synthetic inputs in a separate store. Exercise employer changes versus simultaneous roles, late-arriving evidence, identical names and canonical identity remapping. Inspect extraction proposals, deduplication behavior, time fields and returned source references. Record dependency versions and model configuration. Production ingestion and identity records remain untouched.

Adoption requires acceptable evidence correctness, canonical-ID control, candidate/confirmed separation and recovery after corrections. If any is unresolved, report it in the paper and retain the deterministic backend for the demonstration. Installing an engine does not itself satisfy these criteria.

## Approval state

Eva confirmed the revised scope after presentation of this document. Prepare the implementation plan and present its execution method before implementation. Approval of this delivery scope does not mean a Graphiti production migration has been selected.
