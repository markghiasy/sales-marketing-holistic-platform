# Strategic profile demo implementation plan

> Use superpowers:subagent-driven-development for independent modules, with a whole-change review. User approved trying the strategic-profile research; execute without another approval gate.

**Goal:** A source-backed, correctable synthetic business profile connected to general questions and an opportunity subgraph.
**Architecture:** Typed assertion module plus a separate synthetic fixture; existing store, retrieval and Claude provider remain the application seams. Profile review changes only demo memory. UI reuses entity lenses and the shared assistant.
**Tech stack:** Python/Pydantic/Flask, plain JS/Cytoscape, pytest/headless Edge.
**Spec:** ../specs/2026-09-28-strategic-profile-demo.md

## Global constraints
Synthetic only; no new dependency or production data writes. Full evidence/time/subject validation. No pending facts in retrieval. No implied buying authority or willing introductions. Same light styles and reduced motion.

## Review focus
Wrong-subject source quotation; expired/future evidence; stale concurrent review; UI error handling without paid-call loops; requirement match edges mistaken for actual relationships.

## Task 1: Assertions and commercial fixture
- [x] Test RED: malformed quote, unknown subject, future/expired/pending records, third-party subject, extraction validation.
- [x] Implement adapters/network/profiles.py and tests/fixtures/network_strategy.json; load into default scenario only.
- [x] GREEN and self review. Interface: eligible_assertions(data, query, include_pending=False), profile_context(data, query), Extraction schema, prepare_extraction(data, query), validate_extraction(data, query, result, model).

## Task 2: Views and unified entry
- [x] Browser tests for complex-search handoff, graph display, profile evidence/review.
- [x] Implement profile UI and strategy map, update context/assistant/discovery; no paid call from typing or rendering.
- [x] GREEN, screenshots, reduced-motion/mobile checks.

## Task 3: Integration and review
- [x] Test RED: retrieval of company needs without assigning ownership to author, review rejection excludes records, cross-origin paid extraction and stale updates.
- [x] Wire profile endpoints, bounded extraction, store review, retrieval and answer strategy_graph.
- [x] Full suite, lint, two small synthetic live calls, independent review, demo restart and handoff docs.

## Execution ledger
- Scope follows approved research; keep existing isolated network worktree.
- No profile score or ability certification. Lexical map candidate relevance is labeled explicitly.

Completed: 469 tests passed, including 17 browser cases. Independent review found graph-coverage truncation, confirmed-subject save, and SSE mutation-response race; all fixed with regressions and scoped re-review. Live extraction: six pending proposals. Live question: source-linked commercial answer and 12-node opportunity graph. Semantic advice remains advisory; see docs/demos/strategic-profiles.md. Four relationship scopes were researched separately and not silently substituted for hop counts.
