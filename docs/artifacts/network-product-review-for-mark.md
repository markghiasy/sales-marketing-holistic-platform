# From conversations to useful network decisions

Product thinking & network demo review for Mark | 28 September 2026 | Prepared by Eva

This demo explores a business question: **given a goal, which people or organizations are relevant, why, and what should we verify or do next?** The graph provides a navigable explanation alongside the conversations and evidence that support it.

The current implementation is a **local synthetic demonstrator with 24 fictional contacts**, including experimental Claude-assisted capabilities. It is not a production rollout or a validated recommendation system. The benefits below are hypotheses for our discussion, not measured commercial outcomes.

## The product direction

The starting point was the small contact-level graph that, as Eva reported, did not meet Mark's expectations. Eva then developed the broader requirements through iterations: a larger, more useful network workspace; relationship exploration; views appropriate to people, organizations and projects; and strategic questions that return explainable candidates.

Our proposed product loop is **goal -> relevant evidence -> people and organizations -> possible access routes -> next verification or action**. Team building is one example. Other business uses include finding a pilot organization, locating a channel partner, understanding a customer's need, identifying resources and deciding whom to approach first.

Five principles guide the demo:

1. Start with the decision someone needs to make, not a generic list of skills.
2. Connect the full network to the current conversation, so exploration has a useful return path.
3. Keep direct interaction, explicit collaboration, introductions and shared context distinct.
4. Make source, subject, time and uncertainty visible where a claim affects a decision.
5. Use the model to organize and suggest; validate consequential claims and future value on real tasks.

## The four relationship scopes

The old visible 1/2/3-hop control has been replaced by overlapping evidence categories. These are selectable scopes, not a ladder of closeness. A person may appear in several at once.

| Scope | What supports it | What it does not establish |
| --- | --- | --- |
| 1. Direct interaction | Recorded contact or observed direct messages for this exact pair | Trust, capability or willingness |
| 2. Collaboration or introduction | Sourced collaboration/introduction, directly or through one person; each leg remains inspectable | That an intermediary has introduced you, or will do so |
| 3. Shared project or team | Membership claims in a shared project context, with temporal overlap labeled | Personal acquaintance or equally active contribution |
| 4. Shared organization or company | Shared employment/advisory affiliation and its period | That two employees know one another or share authority |

The current schema implements project membership and organization affiliation; it does not yet import a separate team roster. Recent-event windows, direct-session minimums and recent/frequency/name sorting are separate controls. A recent import or correction does not refresh an old relationship event. Unobserved pair interaction is shown as unknown. Pending paths remain visibly unconfirmed. Display limits retain complete support paths and report what was omitted.

## How the architecture supports this

**Existing source adapters and identity resolution** are the intended upstream foundation. The demo currently starts from authored fixtures, preserving stable identities, source excerpts, effective dates, observation dates and review state.

**A deterministic evidence layer** constructs temporal graph projections, scopes, contact labels and entity views. Shared rendering and query state support both the small conversation slice and the full network. The renderer is Cytoscape.js; graph layout does not decide what is true.

**A separate bounded retrieval layer** gathers candidate entities, original excerpts, typed paths, work records and strategic assertions for a question. Retrieval is broader than the visible canvas. Local lexical recall and structured filters are inspectable and inexpensive; there is no embedding index, BM25 engine or learned reranker in this demo.

**Claude plans and synthesizes within that evidence boundary.** Structured outputs, source checks, input budgets and coverage labels constrain the response. A temporary opportunity map shows question-specific candidates without writing them into the factual graph. Human review remains required for extracted assertions and consequential interpretations.

We researched Graphiti, Hindsight and GraphRAG, but have not replaced the backend with them. A graph database or heavier retrieval pipeline becomes a useful investment when corpus size and labeled evaluation justify it. The current seams keep that future option open without making it a prerequisite for discussing the product.

## Numbered feature catalogue

Origin labels distinguish Eva's explicit directions, reported Mark feedback and engineering decisions. Research references explain the design rationale; they do not establish that our implementation or business hypothesis has been validated.

### 01. A network workspace that is worth exploring

**Origin:** Eva's explicit visual/product requests following user-reported Mark dissatisfaction.

**Status:** implemented.

**Research:** R9: Cytoscape provides interactive graph rendering; the application must supply evidence and temporal semantics. The specific product behavior remains our design choice.

**Choice/reason:** a force-directed shared Cytoscape graph with progressive labels, typed person/organization/project styling, selection and evidence dock; final palette is light and aligned with Inbox. This retains the exploration appeal of the Obsidian reference without retaining the earlier charcoal theme.

**Value hypothesis:** users may notice useful context beyond the currently open contact and be more willing to investigate it.

**Boundary:** 24 synthetic contacts; display caps and omission counts are readability controls, not a scale benchmark.

**Evidence:** `scripts/onboarding/static/network/graph.js`, `network.css`, `explorer.js`; `docs/demos/network-verification.md` light-theme revision; `tests/test_network_browser.py`.


### 02. One network, accessible from the sidebar and the conversation

**Origin:** explicit Eva/user request for full graph and embedded slice.

**Status:** implemented.

**Research:** R1: Temporal-memory research motivates separating when a claim applies from when it became known. R9: Cytoscape provides interactive graph rendering; the application must supply evidence and temporal semantics. The specific product behavior remains our design choice.

**Choice/reason:** both hosts consume the same projection/client/renderer rather than separately generated pictures. Navigation carries focus, knowledge date and mode; the original conversation is separately retained when graph focus changes.

**Value hypothesis:** inspect broader context and return to the conversation with less interruption.

**Boundary:** the synthetic server uses the familiar Inbox template; it does not replace production with fictional data. Compact view is intentionally bounded.

**Evidence:** `embed.js`, `client.js`, `scripts/network_demo.py`, `tests/test_network_browser.py`, `tests/test_network_strategy_browser.py`.


### 03. Multiple sourced contact labels

**Origin:** explicit Eva/user multi-tag request.

**Status:** implemented.

**Research:** R1: Temporal-memory research motivates separating when a claim applies from when it became known. R4: Organization and buying-role models separate people, affiliations and context-dependent decision roles.

**Choice/reason:** derive simultaneous relationship/function/industry/context labels from eligible assertions; show overflow and source detail, keeping current conversation topic separate. A person can be client and collaborator concurrently.

**Value hypothesis:** a useful relationship or specialization is less likely to disappear behind a single label.

**Boundary:** tags are read-only derived projections; not manual taxonomy editing or proven automated profiling.

**Evidence:** `adapters/network/projection.py`, `search.py`, `discovery.js`, `scripts/network_demo.py`; `tests/test_network_search.py`; `docs/demos/network-explorer.md`.


### 04. A shared entry to exact contact search and strategic questions

**Origin:** explicit Eva/user unified smart-search request.

**Status:** implemented with two distinct behaviors.

**Research:** R6: Expert-search and graph-retrieval work support finding people through source evidence and explanatory paths. R7: Structured outputs and evaluation guidance support bounded interfaces and explicit failure cases, not guaranteed semantic correctness. The specific product behavior remains our design choice.

**Choice/reason:** constrained English/Chinese quick search exposes require/prefer conditions and evidence; unsupported conditions request clarification. Explicit goal/strategy submission hands the question to the assistant. Quick matching remains cheap/deterministic; broad reasoning is deliberate and uses the model.

**Value hypothesis:** users can express a need without first learning filters, while seeing how it was interpreted.

**Boundary:** not universal natural-language understanding; no location claim when location evidence is absent; no hidden paid calls while typing.

**Evidence:** `search.py`, `discovery.js`, `assistant.js`, `tests/test_network_search.py`, `tests/test_network_strategy_browser.py`.


### 05. Four overlapping relationship scopes

**Origin:** latest explicit user direction; research refined semantics.

**Status:** implemented in the synthetic demo; covered by API, semantic and browser regression checks.

**Research:** R2: Shared social contexts and typed-path research explain why a connection exists without proving acquaintance. R3: Tie-strength and brokerage research identify multiple relationship dimensions; hop count alone is insufficient.

**Choice/reason:** Direct interaction; Collaboration or introduction; Shared project or team; Shared organization or company. Keep every supported scope for one candidate; expand eligible relation types beyond the original name search. Event window, direct-session threshold and ordering are separate controls.

**Value hypothesis:** users may understand why a person appears and widen exploration without equating graph distance with closeness.

**Boundary:** shared affiliation is not acquaintance, proposed introduction is not completed introduction, missing observation is not absent relationship. Latest template currently exposes recent event/frequency/name sorts; do not claim task-fit sorting unless final source supplies it.

**Evidence:** adapters/network/scopes.py; projection.py; model.py; explorer.js; tests/test_network_scopes.py; tests/test_network_scope_integration.py; tests/test_network_scope_browser.py.

### 06. A time-aware network with current and historical context

**Origin:** engineering inference to make changing roles reliable, demonstrated in the paper.

**Status:** implemented.

**Research:** R1: Temporal-memory research motivates separating when a claim applies from when it became known.

**Choice/reason:** distinguish system observation time, source date and effective interval; retain concurrent advisory roles and source-backed corrections. Carry Known by/current/history through search, context and assistant.

**Value hypothesis:** fewer decisions based on employment or project information the system could not yet know, while preserving useful older experience.

**Boundary:** one knowledge-snapshot control, not independent two-axis retrospective querying; synthetic authored dates.

**Evidence:** `model.py`, `projection.py`, `retrieval.py`, `profiles.py`; `tests/test_network_projection.py`, `tests/test_network_retrieval.py`; paper sections 3–4.


### 07. Communication history without a trust score

**Origin:** engineering inference; addresses user exploration needs.

**Status:** implemented illustrative metrics; expanded scopes now use exact focus-to-person observations or explicitly unknown metrics.

**Research:** R3: Tie-strength and brokerage research identify multiple relationship dimensions; hop count alone is insufficient.

**Choice/reason:** deduplicate direct messages into sessions, expose reciprocity, active days and coverage; distinguish recent activity from longer history. Raw communication is owner-relative, not magically focus-to-candidate.

**Value hypothesis:** users can distinguish a quiet past collaborator from recent one-way noise before deciding whom to contact.

**Boundary:** 30/180-day half-lives and saturation are engineering defaults, not calibrated familiarity, influence or commercial-value scores. Do not use owner activity to exclude unrelated collaboration evidence.

**Evidence:** `projection.py`; paper section 3; scope report; `tests/test_network_projection.py`.


### 08. Inspectable evidence and explicit review state

**Origin:** engineering inference necessary for trustworthy exploration.

**Status:** implemented.

**Research:** R5: Provenance and attribution models preserve who said what about whom; traceability is not proof of truth. R1: Temporal-memory research motivates separating when a claim applies from when it became known.

**Choice/reason:** typed claims retain original source references, dates, status and separate parallel roles; default factual views exclude rejected/unconfirmed assertions, with an explicit pending inspection layer. Source inspector and keyboard paths make evidence review possible.

**Value hypothesis:** users can check a consequential claim instead of accepting an unexplained edge.

**Boundary:** citation existence and exact quotation do not prove meaning or truth; sources here are fictional.

**Evidence:** `model.py`, `projection.py`, `context.js`, `profiles.py`; `tests/test_network_demo.py`, `tests/test_network_browser.py`, `tests/test_network_profiles.py`.


### 09. Person views that explain context, not only contact fields

**Origin:** explicit Eva/user entity-specific views.

**Status:** implemented.

**Research:** R4: Organization and buying-role models separate people, affiliations and context-dependent decision roles. R5: Provenance and attribution models preserve who said what about whom; traceability is not proof of truth.

**Choice/reason:** assemble tags, roles, shared contexts and relevant source records around the same selected identity/date; include strategic profile below rather than forcing everything into graph labels.

**Value hypothesis:** prepares a more informed conversation and surfaces relevant history.

**Boundary:** authored traits are not inferred personality or verified skill level; LinkedIn exports do not supply contacts' full work histories (documented source limitation).

**Evidence:** `context.py`, `context.js`, `profiles.js`; `tests/test_network_intelligence.py`, `tests/test_network_profiles.py`.


### 10. Organization views that retain organizational ownership

**Origin:** explicit entity-specific views plus user's broader business-goal clarification.

**Status:** implemented.

**Research:** R4: Organization and buying-role models separate people, affiliations and context-dependent decision roles. R5: Provenance and attribution models preserve who said what about whom; traceability is not proof of truth.

**Choice/reason:** show members/functions and organization-bound context; a reported organizational need stays attached to that organization with a claimant, rather than being assigned to the sender personally.

**Value hypothesis:** may help identify target organizations and relevant entry points while avoiding assumptions about employee authority.

**Boundary:** organization membership does not establish buying authority, customer access or individual investment capacity.

**Evidence:** `context.py`, `profiles.py`, `retrieval.py`; `tests/test_network_strategy_integration.py` organization attribution tests.


### 11. Project views for responsibilities, delivery, blockers and follow-up

**Origin:** explicit Eva/user request.

**Status:** implemented.

**Research:** R2: Shared social contexts and typed-path research explain why a connection exists without proving acquaintance. R4: Organization and buying-role models separate people, affiliations and context-dependent decision roles. R5: Provenance and attribution models preserve who said what about whom; traceability is not proof of truth.

**Choice/reason:** source-backed assignments and explicit work updates show recorded delivery, blocked/overdue work and follow-ups; only records directly bound to the selected project count toward its coverage.

**Value hypothesis:** helps prepare a project discussion and identify the next follow-up without reading every thread.

**Boundary:** read-only authored examples, not task editing, a full PM system or productivity judgment from message frequency.

**Evidence:** `context.py`, `retrieval.py`, `tests/fixtures/network_demo.json`; `tests/test_network_intelligence.py`, `tests/test_network_retrieval.py`; `docs/demos/network-intelligence.md`.


### 12. Strategic profiles broader than skills

**Origin:** explicit user correction that Mark/boss goals include prospects, partners, channels, resources and organization access, not just team composition; schema is engineering design.

**Status:** implemented experimental.

**Research:** R4: Organization and buying-role models separate people, affiliations and context-dependent decision roles. R5: Provenance and attribution models preserve who said what about whom; traceability is not proof of truth.

**Choice/reason:** six facets—experience, need, resource, decision role, relationship, constraint—with actual subject, claimant, context, source, time and status. Store conditional offers and lack of authority, not a permanent commercial-value score.

**Value hypothesis:** may answer why this organization/person matters for this goal now.

**Boundary:** authored synthetic assertions; no complete commercial dossier, personality inference or verified purchase intent.

**Evidence:** `profiles.py`, `tests/fixtures/network_strategy.json`, `profiles.js`; `tests/test_network_profiles.py`. The strategic research report saying “not implemented” predates this code.


### 13. Draft assertion extraction with human review and correction

**Origin:** engineering inference from the strategic-profile requirement.

**Status:** implemented experimental, live synthetic extraction probe recorded.

**Research:** R5: Provenance and attribution models preserve who said what about whom; traceability is not proof of truth. R7: Structured outputs and evaluation guidance support bounded interfaces and explicit failure cases, not guaranteed semantic correctness.

**Choice/reason:** explicit Claude extraction proposes at most 12 assertions from bounded eligible synthetic sources; validate exact quote/known IDs/author/date, keep results pending, allow confirm/reject/correct subject with versioned review events.

**Value hypothesis:** may reduce future manual structuring work while retaining a reviewable boundary.

**Boundary:** mechanical checks cannot establish semantic attribution; review changes live in demo memory and reset; no validated extraction accuracy or production connector pipeline.

**Evidence:** `profiles.py`, `agent.py`, `/network/profile/extract` and `/review` in `scripts/network_demo.py`; profile/integration/browser tests; `strategy-live-smoke.json` contains six pending proposals, not six verified facts.


### 14. A bounded strategic network assistant

**Origin:** explicit Eva/user strategic LLM Q&A request.

**Status:** implemented experimental with recorded real synthetic-data calls.

**Research:** R6: Expert-search and graph-retrieval work support finding people through source evidence and explanatory paths. R7: Structured outputs and evaluation guidance support bounded interfaces and explicit failure cases, not guaranteed semantic correctness.

**Choice/reason:** planning → bounded local read-only tools → synthesis; preserve entity/date context and a small follow-up history; source-derived fact excerpts and links separated from advisory suggestions. Shared global/entity entry points.

**Value hypothesis:** may turn scattered information into candidates and a useful next question for a business goal.

**Boundary:** no messages sent, no autonomous outreach or project mutation; no fabricated answer fallback when provider/citation validation fails; semantic advice still needs judgment.

**Evidence:** `agent.py`, `assistant.js`, `scripts/network_demo.py`; intelligence/retrieval docs and tests.


### 15. Retrieve quiet relevant contacts and complete evidence within a budget

**Origin:** engineering response to observed retrieval weaknesses.

**Status:** implemented deterministic retrieval improvements.

**Research:** R6: Expert-search and graph-retrieval work support finding people through source evidence and explanatory paths. R8: Hybrid retrieval and reranking are plausible next components, but improvements must be measured on this corpus.

**Choice/reason:** lexical recall across all 24 contacts plus source/structured work/profile records replaces early activity truncation; evidence selection deduplicates source bodies and preserves complete path bundles using relevance/requirement coverage. Separate retrieval graph from canvas caps. Count actual provider input independently from the 28,000-byte evidence-pack limit; refuse inputs over 18,000 tokens.

**Value hypothesis:** a relevant quiet contact or source may be less likely to be lost behind high communication volume.

**Boundary:** lexical OR is candidate discovery, not semantic or capability verification; no BM25, embedding, learned reranker or large-corpus result.

**Evidence:** `retrieval.py`, `agent.py`; `tests/test_network_retrieval.py`; `docs/demos/network-retrieval.md` supersedes early retrieval report truncation descriptions.


### 16. Make evidence gaps and search coverage actionable

**Origin:** explicit user network-gaps requirement; precise states are engineering inference.

**Status:** implemented.

**Research:** R6: Expert-search and graph-retrieval work support finding people through source evidence and explanatory paths. R7: Structured outputs and evaluation guidance support bounded interfaces and explicit failure cases, not guaranteed semantic correctness.

**Choice/reason:** distinguish matching evidence, searched without match, evidence omitted by budget, and not fully searched; one bounded supplementary lookup can cover previously unsearched terms. Separate explicit from suggested requirements.

**Value hypothesis:** users can decide what to verify next and avoid treating missing data as a definitive absence.

**Boundary:** “matching evidence” means retrieved text, not fulfilled capability/eligibility or confirmed buyer status; editable requirement chips were proposed in research but not established as implemented.

**Evidence:** `retrieval.py`, `agent.py`, `assistant.js`, `strategy-map.js`; retrieval/integration tests; coverage demo screenshot is a stubbed answer, not live model output.


### 17. Candidate access routes with typed path evidence

**Origin:** explicit candidate/introduction-route request, with research constraints.

**Status:** implemented constrained path retrieval and four-scope exploration.

**Research:** R2: Shared social contexts and typed-path research explain why a connection exists without proving acquaintance. R3: Tie-strength and brokerage research identify multiple relationship dimensions; hop count alone is insufficient. R6: Expert-search and graph-retrieval work support finding people through source evidence and explanatory paths.

**Choice/reason:** ordered paths retain each edge/source; distinguish person connections, shared context and historical/unconfirmed paths. A non-owner focus cannot expand through the owner hub into the whole address book.

**Value hypothesis:** shows whom one might ask and what relationship needs confirming before outreach.

**Boundary:** no shortest/optimal introduction guarantee, willingness, permission or success probability; shared company is only a lead.

**Evidence:** retrieval.py; scopes.py; tests/test_network_retrieval.py; tests/test_network_scopes.py; source-backed paths remain complete within display limits.

### 18. An opportunity map that explains a question's candidate evidence

**Origin:** user's business-goal expansion; map design is engineering proposal informed by strategic research.

**Status:** implemented experimental.

**Research:** R4: Organization and buying-role models separate people, affiliations and context-dependent decision roles. R6: Expert-search and graph-retrieval work support finding people through source evidence and explanatory paths.

**Choice/reason:** query requirements connect to actual subject entities via dashed candidate edges; solid recorded relationships remain distinct. Requirement buttons highlight relevant evidence cards, sources and gaps. Temporary matches do not mutate the fact graph.

**Value hypothesis:** may help Mark see which potential pilot, channel or resource lead is worth validating and why.

**Boundary:** candidate map is not proof of opportunity, authority or willingness; bounded records/nodes/edges and explicit omitted-source counts. Staged animated replay was proposed in research; current source supports requirement highlighting, not a demonstrated stage-by-stage animation.

**Evidence:** `strategy_map.py`, `strategy-map.js`; `tests/test_network_strategy_integration.py`, `tests/test_network_strategy_browser.py`; recorded desktop/mobile images.


### 19. Reproducible demonstrations, freshness and research artifacts

**Origin:** engineering inference for a concrete Mark/supervisor discussion.

**Status:** implemented.

**Research:** R7: Structured outputs and evaluation guidance support bounded interfaces and explicit failure cases, not guaranteed semantic correctness. R1: Temporal-memory research motivates separating when a claim applies from when it became known.

**Choice/reason:** isolated fixture server, visible synthetic labeling, simulate reply/reset with monotonically changing revision, SSE snapshot refresh, accessible navigation, narrow-screen/browser checks, saved live-response replay and editable paper/demo scripts.

**Value hypothesis:** stakeholders can question behavior on inspectable scenarios before private-data integration.

**Boundary:** in-memory revisions, limited executed browser paths and tiny handcrafted cases; not durability, performance, extraction or customer validation.

**Evidence:** `scenario.py`, `client.js`, `scripts/evaluate_network_demo.py`, `scripts/check_network_agent.py`, `scripts/capture_network_intelligence.py`, `docs/demos/*md`, `docs/papers/temporal-relationship-memory/*`.



## What has actually been demonstrated

- Deterministic scope and integration checks cover overlapping scopes, exact-pair metrics, late knowledge, identity corrections, historical membership, pending introductions, owner-hub avoidance and complete bounded paths. The final local suite passed **505 tests in 152.84 seconds**, including six dedicated browser tests for the new scopes. These tests establish the checked implementation behavior, not recommendation quality.
- A recorded real Claude extraction call over synthetic evidence produced **six pending proposals** (3,301 input / 687 output tokens). These were proposals, not six independently verified facts.
- A recorded strategic answer used **16,398 input / 985 output tokens**. This demonstrates a working integration, not accuracy, latency or cost superiority. The configured demo model is `claude-haiku-4-5-20251001`.
- Seven authored temporal/context diagnostics matched 7/7 expected sets versus 3/7 for each deliberately limited contact-card baseline. This is a narrow policy check, not a held-out benchmark against strong competing systems.
- Graphiti extraction was not executed: its preflight recorded missing prerequisites. Hindsight was researched rather than installed as the demo backend.

## Limitations that shape the next investment

The demo uses authored synthetic data and in-memory review changes. Production source integration, durable review/audit storage, permissions and correction propagation need dedicated work. LinkedIn connection exports can supply limited current company/title information; they should not be presented as the complete employment history of every contact. Account-owner exports and contact data are different sources.

Source existence and exact quotations are necessary but insufficient for meaning: an occupational role is not automatically a buying role; a shared organization is not an introduction; lexical coverage is not proven capability. Model advice can still overinterpret a source. The next evaluation should measure these semantic errors explicitly.

Proposed work remains separate from delivered functionality: hybrid lexical/dense retrieval with reranking; editable goal requirements; richer opportunity-map animation; complementary team selection; manual taxonomy editing; production extraction and real-source permission controls. None is claimed as completed here.

## A useful discussion with Mark

A short walkthrough can follow this sequence:

1. Open a conversation and move from its small graph to the network workspace.
2. Focus a person and expand each scope; inspect a shared-company result whose direct interaction is unknown.
3. Compare a person's context with an organization view and a project's responsibilities, blockers and follow-ups.
4. Ask a business goal, such as finding a pilot organization and an entry route. Inspect candidate evidence, suggested requirements and unresolved gaps.
5. Inspect one pending extracted assertion, correct its subject if needed, and decide whether to confirm it.

The most valuable next input is a small set of real decisions Mark and his team want help with: pilot discovery, partnership/channel access, account preparation or project follow-up. For each, record the expected useful candidates, evidence requirements, misleading suggestions and acceptable cost. Then run a held-out comparison before selecting a more complex retrieval architecture.

Success should mean **a better next decision with less evidence-gathering effort**, measured through candidate relevance, evidence/attribution correctness, complete access paths, honest gaps and user judgment. More nodes or a more fluent answer alone are not success criteria.

## Research and design references

Sources motivate design choices; they do not validate this implementation or its business benefits.

- **R1 Temporal memory:** [Zep paper](https://arxiv.org/abs/2501.13956), [Graphiti edge schema](https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py), [Hindsight paper](https://arxiv.org/abs/2512.12818).
- **R2 Context and typed paths:** [Feld 1981](https://smg.media.mit.edu/library/Feld.SocialTies.pdf), [PathSim](https://www.vldb.org/pvldb/vol4/p992-sun.pdf).
- **R3 Relationship dimensions and bridges:** [Granovetter 1973](https://cpi.stanford.edu/_media/pdf/Reference%20Media/Granovetter_1973_Social%20Networks.pdf), [Gilbert & Karahalios 2009](https://projects.csail.mit.edu/hci-reading/papers/chi09-tie-gilbert.pdf), [Burt 2004](https://snap.stanford.edu/class/cs224w-readings/Burt04StructureHole.pdf). No imported relationship-strength coefficients or introduction-success probabilities.
- **R4 People, organizations and buying roles:** [W3C ORG](https://www.w3.org/TR/vocab-org/), [Webster & Wind](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/04/7215_A_General_Model_for_Understanding.pdf).
- **R5 Provenance and attribution:** [PROV-O](https://www.w3.org/TR/prov-o/), [Web Annotation quotation selectors](https://www.w3.org/TR/annotation-model/#text-quote-selector), [FactBank](https://catalog.ldc.upenn.edu/LDC2009T23). Traceability is not semantic truth.
- **R6 Evidence-first retrieval:** [Balog et al. expert search](https://krisztianbalog.com/files/sigir2006-expertsearch.pdf), [GraphRAG local search](https://microsoft.github.io/graphrag/query/local_search/), [G-Retriever](https://arxiv.org/abs/2402.07630). Retrieval methods do not verify expertise or demand.
- **R7 Bounded model interface and evaluation:** [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations), [agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
- **R8 Future retrieval components:** [Sentence Transformers retrieve/rerank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html), [Elastic RRF](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion), [Anthropic contextual retrieval](https://www.anthropic.com/engineering/contextual-retrieval).
- **R9 Renderer:** [Cytoscape.js](https://js.cytoscape.org/). It renders graphs; it is not the evidence or temporal reasoning engine.
