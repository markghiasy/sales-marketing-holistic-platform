# Adaptive graph search: closest related methods

Checked: 2026-09-30. Primary-source method comparison, not an exhaustive novelty review or reproduction. The proposed residual-requirement policy has not been evaluated.

## Connected subgraph retrieval

**G-Retriever, arXiv v3, Sections 5.1–5.3.** Embeds both nodes and edges, retrieves query-similar items, assigns rank-based prizes, and uses prize-collecting Steiner tree (PCST) optimization to balance relevance against edge cost while connecting the retrieved subgraph. Edge prizes are handled through cost adjustment or virtual nodes. Thus connected, relevant, size-controlled graph retrieval is established. Its reported objective uses fixed query-derived prizes, rather than updating explicit unmet-requirement coverage during exploration. A retrieval-only PCST adaptation is a useful structural baseline; it is not a reproduction of the complete GNN/soft-prompt system. [Paper](https://arxiv.org/html/2402.07630v3)

## Iterative exploration and missing-evidence feedback

**Think-on-Graph 2.0, arXiv v7, Section 3 and Appendix A.** Alternates relation/entity exploration with context retrieval, retains top candidates, and checks whether accumulated knowledge supports an answer. Crucially, its query-reform prompt explicitly asks for additional evidence still needed and a query to retrieve it. The loop emits new clues when knowledge is insufficient. Therefore, “keep searching according to what is missing” is not an unoccupied contribution. The closer experimental question is whether an explicit, auditable residual vector and budget policy improve on free-text clue refinement. Use a bounded ToG-2-style controller with the same tools and evidence, documenting adaptations. [Paper](https://arxiv.org/html/2407.10805v7)

**ARK, arXiv v2, Sections 3–3.1.** Models retrieval as an interaction trajectory conditioned on the query and previous observations. The controller switches between global lexical search and one-hop neighborhood exploration; global access remains available after initial seeding. Neighborhood calls already support node-type and relation-type filters plus subquery ranking. Calls have a result budget, while the trajectory ends at finish or its length limit. This closely matches the desired flexible jumps between aspects and graph regions. Its main output is a ranked node list. A same-tools, same-model ARK-style agent is a stronger controller baseline than static expansion alone. Typed traversal and adjustable breadth/depth must not be claimed as ours. [Paper](https://arxiv.org/html/2601.13969v2)

**GraphSearch, arXiv v2, Section 4.** Decomposes queries, refines context, and grounds later subqueries using prior answers. Its reflection router drafts a reasoning chain, verifies grounding and consistency, and generates extra subqueries targeting missing evidence. It combines semantic queries over text chunks with relational queries retrieving structural subgraphs. This is another direct precedent for evidence-gap-directed hybrid retrieval. Compare with a reflection-based controller; do not equate mere iterative retrieval or explicit gaps with novelty. Its own variation of top-k does not establish equal total model cost for our setting. [Paper](https://arxiv.org/html/2509.22009v2)

## Diffusion and query-conditioned traversal

**HippoRAG 2, arXiv v1, Sections 3.3–3.5.** Uses query-to-triple dense matching, LLM triple filtering, and personalized PageRank over phrase/passage nodes to rank passages. If triple filtering returns none, dense passage retrieval is used. This is a useful associative-retrieval baseline; avoid describing it as query-independent simply because graph construction is offline. Its seeding/reset probabilities are query-dependent. [Paper](https://arxiv.org/html/2502.14802v1)

**CatRAG, arXiv v1, Sections 2.3 and 3.** Adds weak symbolic anchors, query-conditioned weighting of selected outgoing seed edges, and support-triple passage boosts before PPR. The paper explicitly describes one-shot modification before traversal. It does not establish that only our proposal can use evidence or query-specific paths. A one-shot weighting baseline isolates the value of subsequent residual updates; label simplified implementations as adaptations. [Paper](https://arxiv.org/html/2602.01965v1)

## Implications for the framework

The defensible hypothesis is narrow: **does explicitly accounting for residual requirement coverage, evidence admissibility, and remaining budget improve frontier selection over strong adaptive controllers?** Algorithmic novelty remains unverified. Coverage tracking also overlaps xQuAD and team-formation heuristics already checked in the [earlier note](2026-09-29-short-paper-novelty-boundary.md).

Give all controllers identical graph access, source eligibility, model, and initial requirements. Report quality/cost curves across expansion, token, tool-call, and wall-time budgets; top-k alone is not comparable compute. Include ablations with fixed residual priorities and free-text feedback. Measure supported coverage, path validity, unsupported recommendations, and explicit unresolved requirements. Separate typed structural connectivity from justified introductions or verified capability. Search exhaustion means “not found within this budget,” not “absent from the entire network.”
