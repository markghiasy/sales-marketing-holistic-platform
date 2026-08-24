# Handover — Comms & Outreach Platform, Phase 1

Written 2026-08-24, for picking this up in a fresh conversation (memory/context about to be cleared). Read this first — it's the source of truth for "where things actually are," not the git log or the artifacts sent to Mark, both of which lag behind this.

## Where this sits in Mark's build plan

Full build plan PDF: `C:\Users\Eva Ng\Desktop\ironman\Comms & Outreach Platform — MVP 1.0 Build Plan.pdf` (16 pages). Read §7 (store schema), §8 (identity resolution), and §14 (blocks/checkpoints) before touching identity work — don't rely on secondhand memory of these, the exact wording matters (e.g. rule 5 is "never automatic," rule 3 is explicitly called out by Mark as likely to resolve "a large share" on its own).

**Block A** (repo, schema, envelope, Outlook adapter, contacts ingest, export, pipe-health) — functionally done. Outlook adapter now does a correct full backfill + incremental delta.

**Block B** (aggregator client, WhatsApp adapter, LinkedIn adapter, resolution v1 + contacts bridge, parser tiers 1–2, graph views) — WhatsApp and LinkedIn adapters are built and have real synced data. Resolution v1 has NOT been built yet — this is the next task, plan already agreed with Eva (see below).

This block boundary from §14 was rediscovered late (2026-08-24) — worth flagging to Mark that Block A/B labels in past updates weren't tracking the brief's actual block definitions.

## Real data currently in the store

| Channel | Messages | Identities |
|---|---|---|
| Outlook | 4,769 | 1,215 |
| LinkedIn | 1,432 | 232 |
| WhatsApp | 930 | 119 |

Outlook's 4,769 covers full real historical mail (2020–2026), synced with correct original dates — not the "today" import-corrupted dates that existed for a while (see below).

## The big thing that changed this session: Outlook auth

**Original app registration (`comms-outreach-platform-phase1`, multi-tenant + personal accounts, no verified publisher) cannot authenticate against this personal Outlook.com mailbox at all.** Every flow tried (device code, interactive browser, admin-consent-first) failed with `AADSTS530035` ("signed in successfully but no permission to access this resource"). Root cause: Microsoft blocks unverified-publisher multitenant apps from getting real per-user consent against a personal Microsoft account's mail data, and this holds even after admin-consenting the app within its own tenant.

**Fix in place:** `adapters/outlook/client.py` now uses Microsoft's own first-party, publisher-verified **"Microsoft Graph Command Line Tools"** client id (`14d82eec-204b-4c2f-b7e8-296a70dab67e`), hardcoded — this is not a secret, it's published everywhere Microsoft's own docs discuss script access to Graph, same idea as Azure CLI's own public client id. Do not switch back to the custom app registration for anything touching this mailbox's mail data.

**Second fix, same investigation:** authority must be `https://login.microsoftonline.com/consumers`, not a tenant GUID. A tenant-specific authority issues a token that looks completely valid (right audience, right scopes) but still gets 401'd by Graph's mail backend — personal Outlook.com mailboxes live on consumer infrastructure. Confirmed by decoding a token and finding `unique_name: "live.com#chuqiaowu6@gmail.com"` — the MSA-in-a-directory marker.

**Third thing found (not really "fixed," just worked around):** msal's built-in device-flow polling (`acquire_token_by_device_flow`, and even a hand-rolled retry loop calling it repeatedly) is unreliable in this environment — returns `authorization_pending` as a terminal result after a single poll instead of continuing to block. Every script now polls the token endpoint directly by hand (plain `requests.post` loop per RFC 8628) instead of trusting msal's polling. If a future script hits the same "device code didn't work" symptom instantly after printing the code, this is why — don't waste time debugging the Azure app config again, check the polling code first.

**Token caching:** `client.py`'s `get_access_token()` now uses a simple raw-JSON cache (`adapters/outlook/.token_cache.bin`, despite the name — it's JSON now, not an msal binary blob) instead of `msal.SerializableTokenCache`, which never accepted the device-code flow's raw token response cleanly and silently cached nothing. `scripts/_graph_auth.py` is the same pattern, shared across the one-off diagnostic scripts, caching to `scripts/.graph_token_cache.json`. Both are gitignored.

## Second big thing: Outlook delta sync was silently truncating

Found by tracing every page of a fresh delta call by hand: `/me/mailFolders/inbox/messages/delta` on this mailbox stops after ~50 items total and hands back a deltaLink as if that were everything — regardless of how many messages are actually in the folder (confirmed against a 4,769-message inbox). This appears to be a personal-account-specific behavior of the delta endpoint, not a bug in our pagination loop (the loop itself is correct — plain, non-delta listing paginates fine with no such cap).

**Fix in `client.py`'s `fetch_messages()`:** first run (no `delta_link` yet) now does a plain non-delta listing to get everything, then makes one delta call afterward purely to obtain a real `deltaLink` to seed future incremental syncs (the items from that call are discarded — already have them from the plain pass). Subsequent runs with a `delta_link` use pure delta as before.

## Third thing: New Outlook's `.eml` importer corrupts timestamps

This only affects the **Gmail-seeded test data** (imported via New Outlook's Import > Email Files feature to give Eva's test mailbox realistic volume) — not real mail. New Outlook's importer stamps `receivedDateTime` with the *import* time, not the message's real date. The original `Date:` header survives untouched in `internetMessageHeaders`, though.

**Fix in `sync.py`:** `_resolve_sent_at()` now prefers the parsed `Date` header over `receivedDateTime`, falling back to `receivedDateTime` only when no `Date` header is present (real, non-imported mail is unaffected either way since its `receivedDateTime` was never wrong).

Also found and fixed while seeding: New Outlook's importer dumps everything into one destination folder regardless of original Gmail label (so "Sent" mail landed in Inbox too) — this is inherent to the import tool, not fixable from our side, and only matters for this test data, not real sync.

## Fourth thing: WhatsApp `@lid` identity bug (already fixed and merged)

WhatsApp is mid-rollout of an opaque `@lid` identifier standing in for a contact's phone number on some events. 11 contacts had landed as duplicate identities (once under their phone-jid, once under `@lid`). Fixed in `ingest.js` (resolves `@lid` → phone jid at ingest time now) and backfilled via `scripts/merge_lid_identities.py` + `scripts/reingest_pre_lid_queue.py` (already run once, real fix is live). `adapters/whatsapp/node/resolve_lids.js` is the reusable lid-resolution utility if this needs doing again — takes a gitignored input file of `@lid`s now (used to have them hardcoded; that was a real-contact-identifier leak risk, fixed).

## Gmail-seed cleanup (already done)

29,568 emails were imported from Eva's own Gmail (via Google Takeout → `gmail_export/split_mbox_to_eml.py` → New Outlook import) purely to give the Outlook adapter realistic test volume — nothing to do with Mark's actual channels. 24,590 were identified as promo/spam/job-alert noise (Gmail's own labels + a hand-built sender-domain blocklist, both iteratively refined by sampling real data — see `gmail_export/*.log` for the iteration history if the domain list needs revisiting) and deleted via `scripts/cleanup_seed_inbox.py`. This already ran; don't re-run unless re-seeding from scratch.

## Environment / credentials

Real credentials live in `repo/.env` (copied from `C:\Users\Eva Ng\Desktop\ironman\.env.phase1.local`, which is the canonical source — keep both in sync if either changes). `AZURE_TENANT_ID`/`AZURE_CLIENT_ID` in there are now **unused** by the Outlook adapter (superseded by the hardcoded Graph CLI client id above) — still fine to leave in the file, just don't expect them to do anything.

`.env`, `*.local`, all the token cache files, and the files listed above with real contact data are all gitignored — verified before this commit (same rigor as the original pre-push privacy audit).

## Next task: identity resolution v1 (§8) — plan already agreed with Eva

Order agreed, not yet built:
1. Build `/me/contacts` ingest (a small new adapter piece — doesn't exist yet at all)
2. Rule 1 (exact email match) + Rule 2 (exact phone match) — plain SQL against existing `identity` rows
3. Rule 3 (contacts bridge: a contact record with both an email and a phone) — automatic, using the data from step 1. Mark's own framing: this alone should resolve "a large share" of WhatsApp identities.
4. Rule 4 (phone number found in an email signature, regex over `body_text`) — high confidence but writes to `link_candidate` for review before auto-linking, per the brief
5. Rule 5 (LinkedIn name + organisation correlation) — never automatic, always `link_candidate`
6. Rule 6 — everything else stays `person_id = null`. Unresolved is a fine state; a wrong merge is not (this is Mark's own stated priority — optimize for precision, accept low recall early).

## Separate, not-yet-started: knowledge graph scope

Mark asked for §10's network graph to become a real knowledge graph (entities/relationships/facts extracted from messages, e.g. "X reports to Y" — not just message-volume ranking). He explicitly delegated the scoping decision to Eva, on the condition her final design is reasonable and she can explain it to him. Not started — see memory file `project_knowledge_graph_scope.md` for the full framing (should still exist unless memory was fully wiped along with this conversation). Recommended direction discussed but not committed to: closed vocabulary of fact types (not open-ended extraction), reuse the `action`/`outreach` tables' confidence+verdict pattern rather than inventing a new one, probably needs a real graph database for the entity/relationship layer specifically (unlike §10's graph, which stays SQL views per Mark's own framing for that one).

## Housekeeping done alongside this handover

- Removed four throwaway diagnostic scripts (`check_delta_response.py`, `check_import_data.py`, `check_inbox_count.py`, `trace_pagination.py`) — their findings are now captured as comments in `client.py`/`sync.py`, no ongoing value in keeping the scripts themselves
- `.gitignore` extended to cover the WhatsApp `@lid`-related files that carry real contact identifiers, and the DB backup dump from the lid-merge migration
- `resolve_lids.js` parameterized to read its lid list from a gitignored input file instead of a hardcoded list of real contacts' identifiers

## Time spent so far

~13h43m of active work across 2026-08-18 through 2026-08-24 (self-tracked via `time_tracker.py` against this session's own transcript — see that script and its known limitations, e.g. it can't distinguish "reading closely" from "background wait," documented in its own conversation history if that matters later).

## Working style notes (durable, not just this session)

- Confirm the plan before executing anything non-trivial; fix bugs found mid-execution freely, but stop and re-confirm before swapping in a "better approach" mid-flight
- Always give enough context to actually follow what's happening — this user reads and wants to understand the reasoning, not just get a result
- Verify against real data/real UI before trusting documentation or assumptions — this project has been bitten multiple times by "the docs/my assumption said X, the real thing did Y" (Outlook delta pagination, LinkedIn export manifest, the timestamp corruption, the auth flows above)
