# Short-paper novelty boundary: aspect-directed graph retrieval

Date: 2026-09-29. Primary-source check, not an exhaustive novelty review. No proposed method has been evaluated here.

## Prior work that limits the claim

**xQuAD (Santos, Peng, Macdonald, Ounis; ECIR 2010).** Section 3 and Algorithm 1 explicitly combine query relevance, aspect importance, coverage, and novelty. After each selected document, the algorithm updates the information mass already covering each aspect, reducing incentives to repeat covered aspects. Consequently, “track remaining aspects and change priorities” is not independently new. Its immediate output is a diversified ranking from an initial document candidate set. The precise ECIR formulation should not be silently replaced with a later xQuAD variant. [Author-hosted paper](https://terrierteam.dcs.gla.ac.uk/publications/ecir2010_rodrygo_div.pdf)

**Finding a Team of Experts in Social Networks (Lappas, Liu, Terzi; KDD 2009).** The task already combines required-skill coverage with graph communication cost. Section 6.1's GreedyDiameter/GreedyMST heuristics iteratively select people using newly covered skills relative to communication cost, including connecting paths. Therefore, “cover missing capabilities while selecting a connected team” is also established. Their formulation uses a weighted people network and skill membership, rather than our proposed typed, source-supported claim paths. That distinction is an application/model difference, not proof of algorithmic novelty. [Author-hosted paper](https://cs-people.bu.edu/evimaria/cs591/lappas09finding.pdf)

**CatRAG (2026 preprint, v1).** It adapts HippoRAG 2 with symbolic anchoring, query-aware weights on outgoing seed-entity edges, and key-fact passage boosts. The authors describe a one-shot graph modification before traversal, explicitly contrasting it with iterative retrieval. Thus query-dependent edge weighting and evidence-oriented graph retrieval are already occupied territory. [Primary preprint](https://arxiv.org/html/2602.01965v1)

## A bounded, testable increment

Study whether **routing a limited graph-expansion budget using residual requirement coverage, while enforcing typed evidence-path constraints**, improves supported coverage compared with diversifying a fixed candidate pool or weighting edges once. The output is an evidence-connected subgraph plus explicitly unmet requirements; structural connectivity must not imply acquaintance or proven capability.

Specify the expansion state, residual update, admissible edge types, path-evidence checks, priority function, and stopping rule. Hold the underlying graph, extraction, query aspects, evidence eligibility, and answer generator constant. An analyst can supply aspects initially to isolate retrieval from LLM decomposition errors. Novelty of this combination remains unverified; broader work on constrained subgraph retrieval, adaptive search, and team formation must still be checked.

## Necessary comparisons and scope

1. Hybrid retrieval plus bounded fixed expansion.
2. The same candidate pool with an explicitly identified xQuAD-style diversification variant, followed by identical evidence validation.
3. A coverage-versus-connection-cost greedy team baseline, with adaptations documented.
4. One-shot query-conditioned weighting/PPR; label an adaptation as such, not a faithful CatRAG reproduction.
5. Ablations fixing residual priorities and disabling typed evidence constraints.

Match expansion budgets and report end-to-end latency, model tokens/calls, supported requirement coverage, unsupported recommendations, path validity, and unmet-requirement accuracy. Evidence constraints should not be withheld from every baseline. Use held-out queries and independent human evidence judgments; synthetic cases alone support controlled feasibility, not broad industrial effectiveness.

A defensible short paper can contribute a precise task, bounded method, and small reproducible evaluation. Neither publication acceptance nor a “first” algorithm claim follows from this check.
