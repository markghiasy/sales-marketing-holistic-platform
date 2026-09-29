# Relationship scopes and product artifact implementation plan

> Execute with superpowers:subagent-driven-development; user approved implementation. Independent backend and UI modules followed by root integration, full verification and review.

**Goal:** Replace hop-based UI with meaningful scope evidence and document the entire network demo for Mark.
**Architecture:** Pure scope projection integrates with existing snapshot/service; typed query carries state across views; existing graph renderer unchanged. Source paths determine results and display bounds. Artifact is a portable local HTML document plus Markdown, not a production deployment.
**Spec:** ../specs/2026-09-28-relationship-scopes.md
**Tech stack:** Existing Python/Flask/Pydantic/Cytoscape/vanilla JS/pytest/Edge.

## Constraints
Synthetic data only. Preserve current/history knowledge cutoffs, owner/focus distinction and no owner intermediary. Missing familiarity cannot become zero score. Sources and graph paths remain resolvable. No shared branch merge or external publication.

## Review focus
Unknown interaction pair; disjoint project periods; pending intermediary; old URL/slice state; bounds cutting support path.

## Tasks
- [x] Backend scopes.py/model.py TDD: four categories, multipathoverlap, wrongpairmetrics, recency/frequency, sameorgunknown, differentprojectperiods, pending/future/correction, ownerhub, boundedbundles.
- [x] UI template/client/explorer TDD: fourcheckboxes, window/sort/directsessions, meaningfulrows+paths, nohopcontrols, preservedhistoryandroundtrip, keyboard/mobile.
- [x] Root projection/APIintegration: sourceavailability, messagesourcedevidence, defaultbehaviorregressions; runfullsuite and independentreview, inspectscreenshots; restartdemo only when APIidle and warn first.
- [x] After implementation: auditwholefeatureinventory, write English numberedartifactwithorigins/research/decisions/value/limits; generateHTML andvalidate content/navigation/printlayout, linkdeliverables.

## Ledger
- Reusing clean codex/network-demo-paper worktree at4453028.
- Native Claude artifact connector unavailable; portable HTML and Markdown fulfill the requested artifact without unrequested publishing.

- Final verification: 505 tests passed in 152.84s; six new scope browser cases. Independent review fixes: knowledge-time evidence endpoint, explicit-pair identity canonicalization. Both local demo ports 5055 and 5056 now serve the current contract. HTML artifact has 19 feature cards, valid navigation anchors, responsive layout and print styles.
