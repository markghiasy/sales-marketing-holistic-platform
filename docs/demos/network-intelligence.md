# Network intelligence demo — 28 September 2026

> Update, 28 September 2026: user-facing hops have been replaced by [four relationship scopes](relationship-scopes.md). Earlier hop descriptions below describe the preceding iteration.

Purpose: show Mark how a network supports an actual decision, and give the research
draft a testable interface between evidence, graph queries and language reasoning.
The user authorized trying the configured Anthropic API on synthetic data.

## Design and implementation sequence

1. Expand the selected entity against all temporally eligible claims, independent
   of the name search used to locate it. Offer 1–3 graph hops and a separate
   activity threshold. Do not traverse the owner hub unless it is the focus;
   otherwise every contact would appear as a misleading second-degree discovery.
   Shared organization/project paths indicate context, not a proven acquaintance.
2. Build entity views from the same evidence snapshot. People show shared context;
   organizations show functions and members; projects show explicit assignments,
   recorded deliverables, blockers and follow-ups. Activity means exchanges with
   the owner, not productivity. Add clearly fictional project work records.
3. Add a bounded Anthropic agent: one structured retrieval-planning call, local
   read-only tools, one structured synthesis call. At most four tool requests,
   two model calls, validated entity/evidence references, no production database.
   Unknown capability is an evidence gap, not proof that the network lacks it.
   Recommendations are separated from sourced findings. The graph and global
   search both open the same assistant with selected entity/date context.
4. Test expansion/filter regression, historical visibility, project semantics,
   agent references and request bounds using a fake provider; then a small live
   Cybertest strategy test. Browser-check the light UI and independent review.

The first version is an evidence-backed strategy assistant, not an autonomous
outreach agent or a complete project management system. It never sends messages
or mutates project records. Answer context stays in browser memory for the current
conversation and carries the selected knowledge date.

## Implemented boundaries

- Local API key loaded only by explicit `--env-file` or process environment;
  browser sees configuration status and model name, never credentials.
- At most two model calls, four lookups, forty source records, 3,000 output tokens
  per call, and twenty questions per server process. One question runs at a time;
  SDK timeout is 45 seconds per call with automatic retries disabled.
- Planner searches sourced tags/names or requests a specific entity context.
  Retrieval drops verbose rendering metadata; owner-hub expansion is refused by
  the agent tool because it provides little introduction-path information.
- Citation IDs must be in the retrieved source pack. The fact lane displays the
  source excerpts verbatim, and entity links are derived from those records.
  The generative summary and next steps remain advisory; this does not validate
  their semantic correctness or guarantee a useful recommendation.
- Four-turn browser history is bounded and stays in memory. Same-origin JSON,
  trusted loopback hosts and a 150 KB body cap protect the local paid endpoint.
- Project records are explicitly authored fictional updates. These are read-only
  views, not a task editor or an assessment of employee performance.

## Verification observations

Live testing initially exposed unsupported source references and overconfident
role-to-capability inferences. Enum-constrained source selection and deterministic
source excerpts/links address the mechanical failure modes. Human evaluation of
strategy quality remains necessary. One compact Cybertest retrieval reduced input
from 27,928 to 10,451 tokens compared with the first successful broad retrieval;
these are individual runs, not controlled comparative evidence.

Independent review also caught unrelated entity links and a body-size limit too
small for escaped Chinese history. Regression tests now cover both.

Final verification: 349 tests passed (including ten browser flows), Ruff passed,
and desktop/mobile assistant captures were visually inspected. The final live
Haiku smoke test used 7,037 input and 1,015 output tokens over two calls; its
source-derived output is saved in `docs/research/network-demo/agent-cybertest-live.json`.
Earlier failed experiments also consumed tokens; these figures are one successful
run, not the aggregate session cost. No paid model calls run in automated tests.
`scripts.capture_network_intelligence` replays that saved live response for
repeatable screenshots, visibly marked as recorded, without further API calls.

Retrieval remains preliminary: people are selected by literal OR terms over
sourced tags/names, then truncated in activity order; sources are truncated in ID
order. These policies are not semantic relevance ranking. The follow-up research
examines requirement coverage, hybrid retrieval, reranking and token-aware context
selection before claiming broader question-answering quality.

Anthropic integration follows the existing ai_brief.py forced-tool convention;
see https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools.
