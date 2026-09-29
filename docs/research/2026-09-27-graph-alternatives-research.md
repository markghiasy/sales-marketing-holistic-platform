# Temporal graph and agent memory architectures: adoption evidence

Checked 2026-09-27. Scope: primary-source desk research for Ironman's evolving personal relationship network. No packages installed or implementations executed. Recommendations below are architectural judgments, not benchmark results for this product.

## Recommended shortlist

Evaluate Graphiti first for a typed, evolving relationship graph. Evaluate Hindsight instead if conversational memory and retrieval become the main product requirement, particularly when retaining a PostgreSQL deployment is important. Do not introduce both by default. Keep a simple SQL-derived graph as the comparison baseline. This revises the earlier assumption that implementing the graph entirely in PostgreSQL should necessarily come first; it is a proposed evaluation, not an approved migration.

## Graphiti / Zep

**Architecture.** Graphiti ingests episodes incrementally, extracts entities and fact edges, and retrieves with semantic, lexical and graph signals. It supports custom entity/edge types. Its open-source implementation and Zep's managed product are distinct; hosted-product scale claims do not establish the same properties for this deployment. [Official repository](https://github.com/getzep/graphiti), [Custom types](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types), [Search](https://help.getzep.com/graphiti/working-with-data/searching)

**Temporal evidence.** Entity edges contain episode references and created_at, expired_at, valid_at and invalid_at fields. This supports separating when a relationship applied from when the system recorded or invalidated it. An episode reference supplies provenance, not a guarantee that an extracted assertion or time is correct. [Edge source](https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py)

**Integration boundary.** Existing confirmed person/organization facts can enter through explicit triples; however, add_triplet attempts node/edge deduplication. Passing an existing UUID is not sufficient evidence that all identity-resolution behavior will match Ironman's rules. The spike must test canonical-ID mapping, same-name people, multiple simultaneous jobs, contradictory statements and merge/undo propagation. [Triple API](https://help.getzep.com/graphiti/working-with-data/adding-fact-triples)

**Operational tradeoff.** Current documented graph backends include Neo4j, FalkorDB and Neptune; PostgreSQL is not among those supported backends. Adopting Graphiti therefore normally adds a graph store to Ironman's existing PostgreSQL source of truth. The potential benefit is reuse of temporal extraction and retrieval machinery, not automatically fewer services. It also requires LLM and embedding configuration. [Requirements and provider configuration](https://github.com/getzep/graphiti)

**Fit (judgment).** Strongest candidate for this particular people/organization/project graph. Use it behind an adapter as a derived extraction/search layer. Keep original messages, canonical identities, accepted/rejected assertions and reversible merge history authoritative in Ironman. Extraction proposals must not silently become reviewed facts. Whether candidate and accepted views can be separated cleanly is an adoption gate, not a verified property of the integration.

## Hindsight

**Architecture.** Retain, recall and reflect organize the memory lifecycle. The paper separates factual memory and higher-level beliefs; current docs describe world facts, experiences, observations and mental models. These categories should not be assumed to match the paper's older schema exactly. [Paper](https://arxiv.org/abs/2512.12818), [Implementation](https://github.com/vectorize-io/hindsight)

**Retrieval.** Semantic, lexical, graph and temporal retrieval feed rank fusion and reranking, with a bounded output budget. This is a concrete reference for Ironman's activation layer: identify relevant evidence through several routes, then select context under a budget. It does not establish a validated relationship-strength formula. [Recall architecture](https://hindsight.vectorize.io/developer/retrieval)

**Storage and fit.** PostgreSQL is the primary backend: pgvector, built-in full-text search, JSONB and recursive CTE graph queries. Official docs list Supabase among tested managed services, but this session did not check our instance's version/extensions or run its migrations. It remains a separate memory schema/service, not an automatic upgrade to existing tables. [Storage](https://hindsight.vectorize.io/developer/storage)

**Semantic boundary.** Its graph connects memory facts through entity, temporal, semantic and causal associations. World/experience classification refers to the agent's perspective, not automatically to Mark's social ego. Its entity resolution includes fuzzy matching, with documented ambiguity risks. Borrow evidence-to-observation separation and retrieval architecture; do not treat it as a turnkey canonical CRM relationship graph. [Retain architecture](https://hindsight.vectorize.io/developer/retain)

## Generative Agents

The research architecture uses a memory stream, retrieval, reflection and planning. Retrieval combines recency, importance and relevance. This is a useful prior for activation rather than inventing all mechanisms independently. Its recency term concerns time since memory retrieval in simulated game hours; copying that coefficient into relationship decay would change the meaning. The paper evaluates believable simulated behavior, not business-contact ranking or trust. [Paper and full text](https://arxiv.org/html/2304.03442v2)

## Microsoft GraphRAG

**Architecture.** Documents become text units; extraction produces entities, relationships, and optionally claims. The graph is clustered with hierarchical Leiden, communities receive LLM summaries, and relevant artifacts receive embeddings. Text-unit references preserve a route to source documents. Default extraction merges entities sharing title/type and relationships sharing source/target, then summarizes their descriptions. Claims can have status and time bounds, but extraction is optional and disabled by default. These are defaults, not the limit of possible custom workflows. [Official dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)

**Retrieval.** Local search combines entity-related graph context and raw text; global search performs map/reduce over community reports; DRIFT expands local retrieval using community context and follow-up questions. This makes it particularly useful for cross-corpus synthesis such as “which themes connect my education and investment contacts?” [Official query documentation](https://microsoft.github.io/graphrag/query/overview/)

**Incremental ingest exists.** The current CLI documents `graphrag update`, with standard/fast update indexing methods. Microsoft's 1.0 announcement describes computing deltas for newly added content and merging them to reduce re-indexing. It is incorrect to call GraphRAG rebuild-only. This evidence does not establish that every arbitrary source edit/deletion, identity split, or invalidated business assertion has the semantics Ironman requires. [CLI](https://microsoft.github.io/graphrag/cli/), [Microsoft announcement](https://www.microsoft.com/en-us/research/blog/moving-to-graphrag-1-0-streamlining-ergonomics-for-developers-and-users/)

**Composable beyond built-in extraction.** Bring Your Own Graph accepts entity/relationship tables, with text units for additional query modes. A workflow can run just community detection and report generation; embeddings enable further search methods. Thus Ironman can retain its authoritative identities and facts and export a graph projection for summaries. [BYOG documentation](https://microsoft.github.io/graphrag/index/byog/)

**Fit and limitations (judgment).** Use as an optional analytical/search projection, especially for community summaries. Do not equate its default edge weight with personal trust, closeness, or current priority: the documented weight sums LLM-derived relationship strengths across occurrences. Separate explicit roles and temporal assertions in Ironman's canonical model; project them into GraphRAG descriptions when useful. Default source/target aggregation is not the desired canonical representation for several separately governed roles between the same people. [Output schemas](https://microsoft.github.io/graphrag/index/outputs/)

**Current maturity.** Public implementation, package, CLI, and extensive docs exist. The current upstream README explicitly says the project is largely in maintenance mode, will not accept new PRs or features, and will receive appropriate bug/dependency/security fixes. It also calls the implementation a demonstration rather than an officially supported Microsoft offering. This is substantially more inspectable than a paper-only idea, but does not establish production reliability for Ironman. [Current official README](https://raw.githubusercontent.com/microsoft/graphrag/main/README.md)

## A-MEM

**Architecture.** A Zettelkasten-inspired graph of memory notes: construct a note with contextual description, keywords/tags and embeddings; retrieve relevant previous notes; ask an LLM to establish meaningful links; update contextual representations of older notes as new memories arrive. Its native organizing unit is the memory note, not the canonical person or organization. The useful transferable idea is incremental association and reinterpretation of evidence. [Authors' paper](https://arxiv.org/abs/2502.12110)

**Available implementation.** The authors provide an MIT-licensed Python memory-system repository and a separate evaluation repository. README examples include note CRUD, ChromaDB retrieval, metadata and automatic evolution. These are available reference implementations; paper benchmark results are not evidence of operational reliability. [System repository](https://github.com/agiresearch/A-mem), [Evaluation repository](https://github.com/WujiangXu/AgenticMemory)

**Code-level cautions.** The inspected `MemoryNote` includes timestamps, last-access, links and evolution-history fields. `process_memory` retrieves five neighbors and requests `strengthen`/`update_neighbor` actions; neighbor context/tags are changed. However, the current initializer also attempts to reset its Chroma collection and starts an empty in-memory dictionary. A schema field named evolution history is not, by itself, an auditable temporal assertion system. These observations come from source inspection, not execution, and require a pinned-version review before adoption. [Official implementation](https://raw.githubusercontent.com/agiresearch/A-mem/main/agentic_memory/memory_system.py)

**Fit (judgment).** Borrow note-to-evidence linking and updating derived interpretations when new evidence arrives. Keep original messages immutable and version derived interpretations. Retain Ironman's person IDs, reversible merges, typed role edges, provenance, confidence and valid-time rules outside this note network. Note timestamps should not be assumed to encode when a business fact was actually true. This can assist function/project discovery without dictating the product's social graph schema.

## TAPE

The official ICDE 2026 accepted-demo list verifies *TAPE: A Temporal Graph-based Memory System for Personal LLM Agents*, by Chengyang Luo, Qing Liu, Wenjie Zhang and Yunjun Gao, in the **demo** category. Its title directly targets temporal personal-agent memory. [Official conference listing](https://icde2026.github.io/demo-papers.html)

The supplied DOI is [10.1109/ICDE65706.2026.00318](https://doi.org/10.1109/ICDE65706.2026.00318). The DOI full text was inaccessible through this research tool. Exact-title, author and GitHub searches did not locate an attributable public implementation or accessible author-hosted paper. Therefore its detailed algorithms, temporal semantics, update strategy, provenance handling, license and engineering readiness remain **unverified here**. This is not a claim that no code exists. Do not promote a third-party abstract into verified architectural detail or label this demo a mature replacement.

## Adoption implication

Proposed evaluation: adapters -> authoritative PostgreSQL messages/identities/reviewed assertions -> replaceable Graphiti adapter and derived temporal graph -> evidence-filtered task retrieval and product ranking -> network UI/brief. Interaction statistics can remain SQL-derived and join at ranking time. Hindsight is an alternative memory-engine experiment, not a second mandatory component.

Use three scenario families: (1) employer changes versus concurrent roles, with late-arriving evidence; (2) cross-channel aliases versus distinct same-name people, including merge undo; (3) a business task requiring a relevant person, a project connection and an inspectable supporting message. Compare accepted-fact accuracy, false identity merges, historical/current distinction, evidence correctness, retrieval utility, ingestion cost and update latency against the SQL baseline. Synthetic data validates mechanics; Mark's selected business questions and expected evidence are needed to assess industrial value. No current source benchmark establishes that value for this product.

For Ironman, preserve one authoritative model of people, organizations, projects and evidence-backed temporal assertions. Treat graph summaries, memory notes, embeddings and per-contact briefs as replaceable derived views. GraphRAG offers a documented route for that separation through BYOG; A-MEM offers ideas for evolving those views incrementally. Neither reviewed default model establishes the required distinction between durable relationship strength and current salience: define and evaluate those separately using Ironman's own evidence and user judgments. TAPE remains a research lead pending accessible first-party implementation details.
