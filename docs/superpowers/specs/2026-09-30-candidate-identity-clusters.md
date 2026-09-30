# Candidate identities and filed-mail coverage

Source: Mark's 30 September review and `2026-09-30-patches-for-eva.md`, based on main 1337533. This is an architectural change: candidate identity equivalence remains separate from confirmed identity and professional relationship graphs.

## Required behaviour

1. Only `exact_email` may merge automatically, subject to existing safety checks. Contact bridge and all other heuristic rules suggest; human confirmation/manual linking still uses the reversible merge mechanism. Preserve historical decisions.
2. Query-time candidate components may contribute provisional sent/received/last-contact statistics only when there are at most 8 identities and at least 50% unique undirected edge density. Deduplicate message IDs. Reject/retire edges immediately changes the next query. Over-limit or sparse components retain their own confirmed-contact statistics and display direct pairs only. Never create a person or merge log during aggregation. Do not infer acquaintance from identity-candidate edges.
3. A contact shows “May also be … on …”, the matching evidence, and a route to human review. Pending data must not silently become an asserted identity or employer. Briefs label provisional statistics and retain message/fact content from confirmed identities only.
4. Candidate-sensitive cached briefs need invalidation when candidate membership or evidence changes, including removals. Existing fragment briefs need regeneration under the new policy; stale content must be visibly withheld until refreshed. No automatic bulk paid LLM backfill during migration.
5. Apply migration 0013 as supplied: retire pending signature-phone candidates only, retaining history and original reasons. Keep signature detection as observation only, with explicit detected/written wording.
6. Outlook defaults to inbox + sentitems. `OUTLOOK_FOLDER_SCOPE=all` discovers eligible folders and descendants, following pagination. Exclude deleted/junk/drafts/outbox and excluded descendants. Preserve the old inbox/sentitems delta files, hash other folder IDs. Resolve built-in folders by stable IDs rather than English display names; a user folder named Inbox must not share the real inbox's cursor. No silent depth cutoff. Keep retry handling. Never ingest a draft even if encountered outside Drafts. Persist delta checkpoints after database commit.
7. New candidates carry run ID, rule version and code revision (or explicit unknown), with per-rule counts available to operators and review UI. An upgrade may inspect old data; do not label these as new-message matches.

## Boundaries and decisions

- No source-data migrations are run on Eva's or Mark's production database in this task. Validate disposable PostgreSQL and mocked Graph/Anthropic interfaces; publish upgrade instructions.
- Confirmed identity groups are included as known equivalence edges when evaluating a component; count every identity toward the cap. Pending edges using retired methods or involving self/hidden identities are excluded. A rejected pair inside a connected component disables aggregation, even if alternative pending paths remain.
- Tests and final independent review precede push. The user already authorized implementation and push; no new approval ceremony is required.
- Network trial PR #4 remains separate. These fixes target the current production inbox and resolution stack; trial integration is a subsequent merge of this branch, not a conversion of candidate links into graph facts.

Microsoft's folder API supports locale-independent well-known folder names and explicit child traversal: [mailFolder](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0), [childFolders](https://learn.microsoft.com/en-us/graph/api/mailfolder-list-childfolders?view=graph-rest-1.0).
