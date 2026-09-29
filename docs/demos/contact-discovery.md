# Contact labels, discovery and graph navigation

Approved follow-up to the network demo, implemented 28 September 2026. This remains a synthetic, locally hosted prototype.

## Behavior

- Inbox rows expose up to three contact labels plus +N; details expose all labels and clickable source excerpts. The current conversation topic is a separate field.
- Relationships, organizations and projects come from the graph's confirmed, temporally eligible assertions. Functions and industries use explicit fictional profile assertions with dated evidence. Employment at a logistics company is not treated as proof of logistics expertise.
- The top search bar and Ctrl/Cmd+K open contact discovery. Interpreted conditions are displayed before results. Required criteria filter; preferred criteria rank, with recent activity breaking ties. Missing preferences are disclosed.
- Results show matched conditions, source messages, conversation links and graph links using stable IDs. Same-name people remain separate.
- Unsupported terms, exclusions and disjunctions ask for clarification. There is no silent fallback to a weaker query and no claim of open-ended language understanding.
- The Inbox sidebar has a Knowledge graph entry. The full graph has Inbox, Search and Graph navigation. Contact-level graph slices remain in the existing detail panel.

## Implementation boundaries

`adapters/network/search.py` holds the pure interpretation, tag projection and matching functions. `ScenarioStore.search()` reads data and revision under one lock. `/network/search.json` validates input and supplies a result contract to `discovery.js`. The UI escapes content, cancels superseded requests and discards results after close. Keyboard focus stays in the search dialog.

The production app does not expose this endpoint or opt into the demo assets. No database schema, production tag records or model provider configuration was changed. Labels cannot yet be edited, and the rule-based parser is not an LLM/RAG implementation. The UI discloses supported search categories and requests clarification outside them.

## Verification and review

Six new backend/API checks initially failed against the missing feature, then passed. Two new end-to-end browser paths initially failed, then all seven browser cases passed. The complete suite passed 338 tests before independent review. Ruff checks and actual desktop/mobile screenshots were also used. The 390-pixel search view had no horizontal page overflow or JavaScript errors.

The independent review identified three Important issues: named relationship targets were interpreted as name filters, CFO was broadened to Accounting, and historical Inbox lists omitted the observation-date query. Focused regressions reproduced the issues. The parser now requests clarification for those unsupported relationship targets/titles, and list loads propagate the same date as details and search.

Review scope rulings: arbitrary language understanding, production persistence/providers/deployment and identity-binding mutations without a demo workflow remain outside this delivery. Existing historical message-stream filtering was not changed; the new labels are time-aware. Screenshots and paper artifacts are verified separately by the implementer.

The seven-case research policy benchmark is separate from these search acceptance tests; its scores do not measure language interpretation.

After review fixes: **340 tests passed in 42.11 seconds**; Ruff passed. The newly added semantic and historical-list regressions failed before their fixes and passed in the final suite. The updated paper build exited successfully and remains eight pages; its changed pages were rendered and inspected. The running local endpoint returned Maya then Priya for the collaboration-preference example.
