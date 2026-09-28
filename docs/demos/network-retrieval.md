# Network retrieval optimization, 2026-09-28

The isolated network demo now searches all 24 synthetic contacts using sourced
profile facts, relationship records, work updates and their original excerpts.
Recent communication activity no longer selects the first twelve candidates for
Claude. Quick search remains the existing bounded condition parser; this upgrade
primarily changes the strategy assistant's retrieval and context handling.

## What to try

Run `python -m scripts.network_demo --env-file path/to/local.env` and open
http://127.0.0.1:5055/network. The existing light interface and Inbox slice remain.
The live provider is `claude-haiku-4-5-20251001`; the demo uses synthetic data only.

1. Ask about Cybertest: authorized adversarial AI-agent security testing for vibe
   coding, relevant contacts, capabilities not established and next outreach steps.
2. Select Harbour expansion and ask who delivered work, what is blocked and what
   needs follow-up. Inspect the cited updates and the coverage details.
3. Switch to Relationship history, select Alex Morgan, then enter Inbox/search or
   the assistant. Historical employer context and mode persist across those routes.
4. Open How this answer was grounded. Matching evidence, no recorded match,
   budget-omitted evidence and requirements not fully searched are distinct states.

## Retrieval and evidence contract

- Two model calls: goal/lookup planning, then synthesis. A deterministic additional
  lookup can search up to eight previously unsearched terms once. Remaining terms
  stay explicitly unsearched; there is no unbounded agent/tool loop.
- All-contact lexical candidate recall searches source excerpts and structured
  records. It is not BM25, embeddings, a semantic reranker or verified capability
  matching. Requirements and require/prefer/exclude priorities guide the model;
  retrieval coverage is not an automated eligibility or suitability verdict.
- Source existence, source date, claim knowledge time, effective dates and review
  state are checked before retrieval. Current/history semantics reach graph,
  context, search, Inbox requests and assistant navigation.
- Neighborhood retrieval uses its own adjacency/BFS, independent of the canvas
  limits. Ordered paths retain all their edges and sources. A non-owner focus
  cannot use the owner as an intermediate hub. Active confirmed person paths are
  distinguished from shared context and historical/unconfirmed paths; none
  guarantees willingness to make an introduction.
- The evidence pack deduplicates source bodies and selects complete bundles by
  requirement coverage and query relevance. Its default serialized source-pack
  limit is 28,000 UTF-8 bytes. The provider separately counts the exact request
  (including system prompt and tools) and refuses input exceeding 18,000 tokens.
  The byte bound is not described as a measured token count. Prior conversation
  is limited to two shortened turns; prior generated advice is not source evidence.
- Project/organization coverage only counts records directly bound to that entity.
  Other projects' deliveries cannot satisfy the selected project's requirements.
  Global candidate recall can still supply outside people as prospective leads.
- Only supplied source IDs may be cited. Entity links derive from packed source
  bindings. The factual lane shows original source excerpts; strategy suggestions
  remain advisory and require human checking for relevance and actual expertise.

Strict schemas use the SDK's transformer, which preserves supported constraints
and describes unsupported bounds for the model; application validation remains.
See the [official schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations).
The package requires Anthropic >=0.125,<1 and explicitly includes httpx in dev
requirements, avoiding the incompatible 1.x transport installed by the first CI run.

## Verification record

The regression suite covers quiet but relevant contacts, work-only matches,
missing/future sources, historical roles and corrections, source-ID renaming,
complete typed paths, budgets, coverage states, supplementary lookup, strict
counted requests, and project-specific coverage. Browser cases exercise history
propagation from both Explorer and Inbox/search. **Final local result: 421 passed, zero skips, including 12 browser cases.**
Ruff, Python compilation and whitespace checks passed. Final Harbour live
verification confirmed no Research Bridge delivery in Harbour coverage.

The live artifact is [retrieval-live-smoke.json](../research/network-demo/retrieval-live-smoke.json).
It retains earlier attempts as well as final results. Initial live attempts exposed
empty or excessive citation lists. SDK schema transformation and explicit citation
instructions fixed the tested cases. A later project smoke test exposed coverage
from an unrelated project; the focused regression and direct-binding rule address
that issue. Passing a few smoke questions is not a statistical accuracy or latency
benchmark, and generative advice can still overstate what a broad role implies.

[Coverage screenshot](network-retrieval-coverage.png) is a controlled browser test
with a synthetic stubbed answer, not a capture claiming live model output.

Quality repairs were merged separately through GitHub PRs 2 and 3. Latest remote
main 1337533 passed CI. Network changes remain on `codex/network-demo-paper` for
local demo/review; no production network deployment or customer-data evaluation
was performed.
