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
