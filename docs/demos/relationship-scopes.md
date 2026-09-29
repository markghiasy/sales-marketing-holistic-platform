# Four relationship scopes - 28 September 2026

This replaces the visible hop/activity controls described in earlier demo notes.

Choose a person, then **Focus neighborhood**. Defaults select direct interaction and collaboration/introduction. **Expand more** adds project context, then organization context. Checkboxes can be combined freely; no selected scope returns only the focus.

- Direct requires observed messages for that exact pair or an explicit In contact claim.
- Explicit paths require collaboration/introduction evidence, directly or via one person. Each directed claim is retained. A suggested introduction is not completed.
- Shared project and shared organization are contexts, not acquaintance. Project membership is implemented; a separate team roster is not.
- Recency, session minimums and scope choice are independent. Session minimum applies only to direct scope; event windows do not hide shared contexts.
- Unknown pair interactions stay unknown. Owner-to-contact statistics are not reassigned to another focus.
- Time corrections and source knowledge cutoffs are enforced. Historical disjoint memberships are labeled.
- Complete path bundles fit within 50 nodes / 100 edges; omissions are reported. Compact conversation slices remain bounded at 8 nodes / 12 edges.
- Old depth/min_activity URLs remain accepted but no longer control explorer expansion.

## Verification

Final local suite: **505 passed in 152.84s**, with an isolated PostgreSQL test database and no model calls. Six dedicated real-API browser cases cover scope controls, URL/history and Inbox round trips, keyboard/mobile layout, exact-pair unknowns, source paths, entity focus and pending separation. Scoped Ruff check passed. Independent review found two integration issues (late-import evidence access and participant alias canonicalization); both now have passing regressions.

The running 5055 process was initially stale while reading updated static files. It was replaced after confirming its command and recent graph activity; both 5055 and 5056 now return scope metadata. Refresh existing tabs.

## Stakeholder artifact

[Product review for Mark](../artifacts/network-product-review-for-mark.html) is a self-contained English HTML file; [Markdown source](../artifacts/network-product-review-for-mark.md) is editable. It covers 19 numbered capabilities with origins, findings, design decisions, expected value and limitations. HTML navigation and narrow-screen overflow were checked in headless Edge. No private source data or credentials are included.
