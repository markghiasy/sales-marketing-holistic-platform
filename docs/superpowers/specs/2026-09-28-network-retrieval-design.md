# Network retrieval: first optimization pass

Continue the approved network demo work using the 2026-09-28 retrieval research.
The goal is a more useful Mark demo: a quiet but relevant contact can be found,
strategy answers inspect actual work/source evidence, and partial searches do not
masquerade as evidence that the network lacks a capability.

This pass improves the existing two-call agent and context views. It introduces
no production connector, vector database, embedding provider, or automatic action.
The first call still plans and the second synthesizes; deterministic retrieval
between them can perform one extra lookup for uncovered requirement terms.

## Retrieval contract

Build evidence-backed records for eligible claims, profile assertions, and work
updates. Apply knowledge date, current/history, review status and source existence
before matching. Preserve claim validity/observation times in records. Search all
eligible contacts by explicit lexical relevance over these records and their
source text, not owner communication activity. Return matched/missing terms;
matching text remains a candidate signal, never proof of specialized ability.

Neighborhood retrieval has its own typed adjacency/BFS and returns ordered paths,
independent of canvas node/edge limits. Do not traverse the owner as a bridge from
another focus. Distinguish confirmed active person-to-person contact paths from
shared organizational/project context and historical/unconfirmed paths. Neither
kind guarantees willingness to introduce someone.

The planner may identify up to eight goal requirements. Coverage reports whether
matching records were included, found but omitted, searched without a match, or
not searched. It is retrieval coverage, not a verdict that a person meets a need.

## Context budget

Select complete record/source bundles, prioritizing uncovered requirements and
query relevance. Select a path only with every edge and source present. Deduplicate
source bodies and serialize each body once. A deterministic UTF-8 byte budget
limits the evidence pack; the provider additionally counts the exact request and
enforces an input-token ceiling before each model call. Never call a byte count
a measured token count. Only selected sources can be cited. Expose omitted counts
and coverage in the assistant's grounding details. Preserve history/current mode
from the graph into context, assistant, evidence and navigation.

## Verification

Regression cases: low-activity relevant person, work-only match, historical role,
late correction/source, missing source, ID renaming, complete multi-hop path,
shared organization versus acquaintance, tiny evidence budget, requirements with
no evidence, and one targeted follow-up lookup. Exercise real SDK serialization
using mocked HTTP and a bounded synthetic live smoke test if configured.
Run the merged full suite and existing browser checks. Report measured outcomes
only; this is a small synthetic demo, not an industrial retrieval benchmark.
