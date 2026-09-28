# Network demo delivery and verification

Implemented in isolated branch `codex/network-demo-paper`, based on `dbd4cbd`.

## Delivered

- Deterministic temporal graph projection with typed IDs, separate claims and source evidence, pending-state filtering, time-aware corrections, reversible fixture identity bindings and bounded views.
- Shared Cytoscape renderer and query client used by the full explorer and an opt-in slice in the existing Inbox template.
- Fictional scenario API, SSE revisions, reply/reset controls, seven reproducible diagnostic scenarios and a five-minute presentation script.
- English supervisor discussion paper: editable Markdown, bibliography, real application screenshots, self-contained HTML and an eight-page PDF.

The production app retains its existing behavior. This branch has not been merged, pushed or deployed.

## Final independent review

The independent reviewer returned **with fixes**, identifying four important issues. One cohesive fix pass addressed all four:

1. Restore the selected claim from the slice URL and update the full-network link immediately on selection.
2. Expose every compact claim to keyboard users and provide an accessible entity selector.
3. Suppress redundant same-version snapshots; preserve expanded evidence and keyboard focus across actual data revisions.
4. Carry the original conversation ID separately from graph focus, so neighborhood exploration does not change the return destination.

Regression evidence: the three added browser tests first failed against the previous implementation, then all five browser tests passed after fixes. No second review cycle was requested.

Final complete suite: **330 passed in 36.46 seconds**. Targeted Ruff checks passed. The paper build completed with exit code zero; PDF metadata confirms eight A4 pages. All pages were visually reviewed during preparation, and the two pages with updated application figures were re-rendered and inspected after the final UI fixes.

Commands used:

```powershell
python -m pytest -q --basetemp=.test-final-verified
python -m scripts.build_network_paper
```

The project virtual environment and installed headless Microsoft Edge were used. Pandoc and the existing PDF renderer produced the document artifacts.

## Limits and remaining research

- Graphiti's engine experiment is **unexecuted**: its SDK and a dedicated graph store were unavailable. The preflight report is `docs/research/network-demo/graphiti-preflight.json`; it contains no model scores or cost claims.
- The seven handcrafted cases diagnose policy behavior; they do not establish comparative research superiority or industrial usefulness. There is no live extraction benchmark or user study.
- The reviewer did not inspect vendor internals, independently revalidate the bibliography, or assess PDF layout; primary-source research and PDF inspection were handled during implementation.
- Browser acceptance covers the executed interaction paths, including real revisions and navigation. An exhaustive delayed-request/reconnect stress matrix and large-scale performance study remain future work.
- Fixture functions are human-authored attributes. Production temporal extraction, identity review integration, authorization and realistic channel coverage need validation before connecting private data.

Next decision: use Mark's real business questions to define the target task and expected useful contacts, then agree on the controlled evaluation with the supervisor. Keep live data integration separate from this synthetic presentation.

## Visual revision following Eva's Obsidian reference

The graph now uses a charcoal canvas, small lavender points, muted gold organizations and sage projects. A force-directed layout replaces overview columns and compact rings. Names appear progressively with zoom, hover and selection; selected edges show relationship labels and direction. The evidence dock is initially closed in the overview and opens on selection. Both hosts retain the same renderer and graph records, with no decorative entities added.

Typography uses the local Segoe UI Variable/Segoe UI stack. The compact view scopes its dark palette locally inside the existing light Inbox. On narrow screens the contact list scrolls horizontally above a full-width map.

Validation: five existing browser acceptance tests passed in 19.09 seconds after the interaction/style changes. Additional actual browser checks covered dock close/reopen, a 390-pixel viewport without horizontal page overflow, and zero JavaScript errors or Cytoscape warnings. Desktop, selected, embedded and mobile screenshots were inspected. The paper was rebuilt with the new figures; the two affected pages were rendered and visually checked. The earlier 330-test full-suite result predates this presentation-only revision.

## Unified light theme, 28 September 2026

At Eva's request the explorer, embedded graph, search dialog, evidence surfaces and navigation now use a light palette aligned with Inbox: white canvas, soft grey panels, muted violet interaction states, gold organizations and green projects. Canvas node and edge colors read the shared CSS variables so the full graph and embedded slice stay consistent. Force layout, selection, filtering, discovery and evidence behavior are unchanged.

Eight browser acceptance tests passed in 29.88 seconds. Visual checks covered overview, selection with evidence, Inbox slice, search results, and 390-pixel graph/search layouts. There were no JavaScript errors or graph-library warnings and no horizontal overflow in the narrow layouts. A residual dark dropdown and low-contrast metadata text found during screenshot review were corrected. Demo screenshots and the paper figures were refreshed.
