# Identity suggestions and filed-mail upgrade

Based on Mark's 30 September review and his two patches against `1337533`.

## What changes

1. **Identity policy.** `exact_email` remains eligible for automatic merging under existing safety checks. Contact bridge, name/company and same-channel matches remain suggestions until a human confirms them. The shared merge entrypoint enforces this rule as well as the individual matcher. Existing merges are not reversed by this release.
2. **Bounded query-time aggregation.** A pending candidate component can contribute provisional sent/received/recency statistics only at ≤8 identities and ≥50% edge density. Duplicate/reversed edges count once, and messages count once even when multiple identities participated. Sparse/oversized groups show direct suggestions while retaining their own contact counts. Rejected pairs veto aggregation through an alternate path. Confirmed person membership remains authoritative; candidate links do not become professional network edges.
3. **Contact evidence.** Open a contact's name in the inbox to see “May also be … on …”, matching evidence, provisional counts and a link to the review queue. Known handles remain separate. The panel displays at most 50 direct suggestions and says when more exist.
4. **Brief freshness.** Candidate topology changes invalidate cached briefs conservatively across the mailbox. Message/fact changes invalidate dependent contacts only. Until regeneration, the inbox withholds outdated summaries/context and displays a notice; the old cache remains stored. New briefs receive conditional aggregate statistics, while message content and facts still belong only to confirmed identities. New-message refresh includes affected cached candidate partners. No migration calls an LLM.
5. **Signature-phone retirement.** Migration 0013 is Mark's retirement patch. It withdraws only pending `email_signature_phone` rows; decided history and original evidence remain. Detection continues for observation, explicitly distinguished from candidates written.
6. **Outlook filed mail.** `OUTLOOK_FOLDER_SCOPE=all` opts into recursive, paginated folder discovery. Default is still Inbox + Sent Items. Built-in IDs protect localized names and prevent custom folders named Inbox from sharing a cursor. Excluded folders and descendants remain excluded, including Deleted Items/Junk/Drafts/Outbox; draft messages are filtered as an additional guard. Existing inbox/sentitems cursor files are reused. Deep folders are not silently omitted. Checkpoints advance only after message commit.
7. **Upgrade attribution.** Newly generated candidates carry a resolution run ID and rule version. Run records include code revision, time, per-rule result counts and failure status. The queue shows this metadata and explicitly notes that suggestions may arise from already stored messages. Historical candidates without provenance remain unknown.

## Upgrade an existing local installation

Use an isolated checkout to inspect this release, or stash/commit local work first. Mark's local patches must be reconciled, not blindly overwritten. Keep the existing `.env`, token cache, WhatsApp state and delta files. Back up PostgreSQL using the existing deployment runbook.

1. Stop the application's scheduled sync and UI processes through the existing deployment procedure before switching code/schema.
2. Install the checked-out project dependencies: `python -m pip install -e ".[dev]"`. The declared Anthropic range is `>=0.125,<1`; validation uses Anthropic 0.125.0 and httpx 0.28.1. A previously installed SDK outside the project's range is not this tested environment.
3. Apply each not-yet-applied migration, in order, with `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f <file>`:
   - `db/migrations/0013_retire_email_signature_phone.sql`
   - `db/migrations/0014_candidate_brief_dependencies.sql`
   - `db/migrations/0015_resolution_run_provenance.sql`
   0013 is safe to repeat; 0014/0015 are one-time schema migrations. If Mark already applied his exact 0013, do not re-create a differently numbered retirement migration.
4. Optional: add `OUTLOOK_FOLDER_SCOPE=all` to `.env`. Leave it at `default` to retain the existing scope. `IRONMAN_RELEASE` is optional for installs without Git metadata; otherwise the running checkout's commit is recorded.
5. Restart the existing sync/UI processes. Run an Outlook sync and inspect its status and `resolution_run` records. First expanded sync can take substantially longer. Folder exclusion controls ingestion scope; it does not erase previously ingested messages.
6. Existing briefs are deliberately marked out of date by 0014. Preview a bounded refresh with `python -m scripts.refresh_identity_briefs --limit 25`; add `--apply` when ready for the provider cost. Repeat batches as needed and inspect `ai_brief_status` for failures. Otherwise touched contacts regenerate during normal sync. Do not mistake an explicit stale notice for lost source messages.

Candidate topology invalidation is deliberately conservative for this first release: unrelated cached briefs can also need refresh after an identity decision. Source messages, identity records and previous cache rows remain stored. Folder discovery fails visibly if it cannot identify required built-in folders, rather than guessing their English names.

The network trial in PR #4 remains a separate branch. These changes target the production inbox/resolution stack and must be integrated into that trial before claiming it has the same candidate behaviour.

## Reply draft (send after the push is verified)

Thanks Mark — I’ve integrated your two patches and the suggestion-first identity policy, with tests around the failure cases you identified.

Only exact-email matching can now merge automatically. The contact panel shows possible matching identities with their evidence, and query-time statistics respect the ≤8 identities / ≥50% density limits without merging records. Larger or sparse groups fall back to pairwise suggestions. Briefs preserve that uncertainty, and outdated results are withheld when their evidence changes.

I also added localized/deep-folder coverage and checkpoint safeguards to the Outlook patch, retained 0013’s surgical retirement, and added run/rule/code attribution to new review items. The automatic-merge quality gate remains in place; it is separate from shipping the suggestion workflow.

The upgrade notes cover the migrations, optional all-folder scope, and brief regeneration. I’ve validated this on disposable test data; your mailbox remains the real-data acceptance check. I haven’t changed your installation or run a paid backfill.
