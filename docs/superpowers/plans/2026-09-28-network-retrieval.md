# Network retrieval implementation

Continue natively in the existing isolated network worktree. Preserve the newly
merged resolution fixes and existing light UI. Design:
`../specs/2026-09-28-network-retrieval-design.md`.

1. Write failing retrieval regressions for full-candidate relevance, sourced work,
   temporal propagation, missing-source rejection and complete typed paths.
2. Add a pure retrieval module: eligible records, people/context/path queries,
   requirement-aware bundle selection and explicit coverage/budget accounting.
3. Integrate planner requirements, one bounded supplemental lookup, strict counted
   provider requests, and safe citations; propagate mode through the context UI
   and assistant and display search coverage.
4. Run targeted tests, independent review, full integration suite and browser/live
   synthetic smoke checks. Record exact verification and commit the demo changes.

The owner authorized resuming the researched network optimization after merging
the quality fix. Further production integration or backend replacement is outside
this implementation pass.
