# Runbook

Kept current at every block checkpoint (build plan §13 rule 7) — this is
what makes the cutover in §14 possible at all.

## Deploying a clean instance

1. `cp .env.example .env`, fill in every value. Nothing here should ever
   come from a file, seed, or migration instead (§5 rule 1).
2. `docker compose up -d` — brings up Postgres and applies
   `db/migrations/` on first boot.
3. `pip install -e .`
4. `python -m adapters.outlook.sync` — first run triggers a device-code
   auth prompt against `AZURE_TENANT_ID` / `AZURE_CLIENT_ID`; sign in as
   `OUTLOOK_MAILBOX`.
5. `python scripts/pipe_health.py` — confirms the store is reachable and
   has ingested at least one message.

A second, independent deploy from a clean checkout and an empty database
standing up and syncing cleanly is the exit criterion for this block, not
a one-time demo (§2, "deploying a clean second instance is a gate at every
block checkpoint").

**Run for real, 2026-08-27/28** — this had never actually been done
before (Block A had been called "functionally done" without it). Fresh
`git clone` of the pushed repo, different Postgres port and password,
`.venv` built from scratch:

- `docker compose up -d` on an empty volume applied both migrations (9
  tables + 4 views) automatically, no manual step.
- Found a real gap doing this: the host port in `docker-compose.yml` was
  hardcoded (`5432:5432`), so a second instance on the same machine as
  an already-running one collided. Fixed to read `${POSTGRES_PORT:-5432}`,
  matching the pattern already used for user/password/db.
- `pip install -e .` — clean, no missing deps.
- `python -m adapters.outlook.sync` against the empty store: fresh
  device-code login (token cache is gitignored, as it should be),
  **backfilled all 4769 messages**. Re-running immediately after synced
  0 — idempotency holds from true zero.
- `scripts/export.py` **failed outright** the first time — see the
  entry above this section; fixed to run `pg_dump` in a throwaway
  container instead of assuming a host-installed client. Re-tested:
  export succeeded, and the resulting dump was restored into a third,
  separate Postgres (different role name) with `pg_restore --clean
  --if-exists --no-owner` — all 4769 messages and their edges came back
  intact.
- `scripts/pipe_health.py` / `scripts/monitor.py` both ran clean
  against the empty store before syncing (correctly reported empty/
  unhealthy, no crash).

Net: the checkpoint passes, with two real fixes shipped as a result
(`export.py`'s pg_dump dependency, and the hardcoded Postgres port).

## Re-running a full backfill

Delete the relevant `adapters/outlook/.delta_link.<folder>.txt` file
(`inbox` or `sentitems`) and re-run `python -m adapters.outlook.sync`.
Idempotency is keyed on `internetMessageId` (see the warning in
`envelope.py`), so this adds zero duplicate rows — safe to do any time
something looks off.

## Rotating the client secret

Not currently used by the adapter (it authenticates as a public client via
device code, no secret in that flow) — but if a confidential-client path
gets added later, rotate in the Entra app registration's Certificates &
secrets blade and update the secret store. Never in `.env`, never in git.

## WhatsApp: first-time setup and ongoing sync

1. `cd adapters/whatsapp/node && npm install`
2. `node ingest.js` — first run has no saved session, so it prints a QR
   and writes it to `qr.png`; scan it from WhatsApp (Settings > Linked
   devices > Link a device). Keep it running — it writes every message to
   `queue.jsonl` as it arrives.
3. `python -m adapters.whatsapp.sync` — drains the queue into the store.
   Safe to run repeatedly / on a schedule; a bare "nothing queued" means
   there's nothing new since the last run, not an error.
4. `python -m adapters.whatsapp.apply_contacts` — backfills
   `identity.display_name` from `contacts.jsonl` (written by `ingest.js`'s
   `contacts.upsert` handler). Same one-time-on-fresh-pairing limitation as
   history (below) — run once after each fresh QR scan, not on a schedule.

**Names are partial, and that's expected, not a bug.** `contacts.upsert`
only reports numbers actually saved in your phone with a name. Confirmed
2026-08-21 against real data: 101 `@s.whatsapp.net` contacts had exchanged
messages, only 16 matched a saved contact name — the rest are real people
who messaged without being saved to your contacts, which `apply_contacts`
correctly leaves nameless rather than guessing. Separately, `@lid` handles
(WhatsApp's newer privacy-preserving id space, ~11 of our contacts) don't
resolve against phone-number-keyed contacts at all — a different problem,
not attempted here.

**Full history only arrives once, right after a fresh QR scan** — Baileys
fires one bulk `messaging-history.set` event on initial pairing and does
not repeat it on ordinary reconnects (confirmed 2026-08-21: reconnecting
to an already-paired session produced zero history, only live events).
There's no on-demand backfill for chats with zero known messages either —
`fetchMessageHistory()` exists but needs an anchor message to page
backward from, so it can't bootstrap a chat from nothing. If historical
volume is needed again later, that means logging out and re-scanning,
not something to do casually mid-project (it also creates a new "linked
device" entry each time).

**Bug found and fixed 2026-08-21:** Baileys' `messageTimestamp` is a
64-bit `Long` object, not a plain number — `JSON.stringify`-ing it into
the queue produced `{"low": <seconds>, "high": 0, "unsigned": true}`
instead of a number, which broke `int()` on the Python side.
`ingest.js` now calls `.toNumber()` before queueing; `sync.py`'s
`_parse_timestamp()` also handles the old broken shape defensively, so
the 688 messages queued before the fix weren't lost.

**Also found:** two duplicate `connect.js` processes (an early throwaway
pairing script, superseded by `ingest.js`) had been running against the
same session folder simultaneously since 2026-08-18, undetected until
this session. Killed before building the real adapter. The standalone
`whatsapp-phase1-pairing/` spike directory outside this repo is now fully
superseded by `adapters/whatsapp/` — safe to delete once nothing else
depends on it.

Verified against real data 2026-08-21: 688 messages, 114 threads, 115
identities (self correctly flagged), 293 outbound / 395 inbound,
idempotent on re-run (second run reported "nothing queued").

## LinkedIn: first-time setup

1. `python -m adapters.linkedin.login` — opens a real browser window, log
   in by hand (password, 2FA, whatever it asks — this script never sees
   the password). Session saves to `adapters/linkedin/.storage_state.json`
   once you land on the feed.
2. Set `LINKEDIN_SELF_NAME` in `.env` to your exact LinkedIn display name
   (used by the export path to tell your own messages apart from theirs).
   For the backup scraping path, also find your member id from your own
   profile URL (`/in/<this part>`) and set `LINKEDIN_MEMBER_ID`.

## LinkedIn: the data-export sync (primary path)

Two separate runs, because LinkedIn's export has a ~24h turnaround and
there's no webhook to drive off of:

1. `python -m adapters.linkedin.request_export` — submits the request.
   Confirmed live on 2026-08-19: select "Download larger data archive"
   (the "pick specific files" option doesn't offer Messages at all), hit
   Request archive, LinkedIn shows "Request pending" and emails you when
   it's ready. Safe to re-run — it detects and no-ops on a pending
   request instead of submitting a second one.
2. `python -m adapters.linkedin.export_sync` — run this again later
   (manually, or on whatever schedule ends up decided). No-ops cleanly if
   nothing's ready yet; downloads, extracts `messages.csv`, and upserts
   once something is.

**Verified against a real archive (2026-08-21):** request submitted
2026-08-19 became downloadable within ~2 days; the on-screen "ready for
download" list only names 5 categories (Articles, Invitations, Profile,
Recommendations, Registration) — **that's not the real manifest**, the
actual zip has 34 files including `messages.csv` and `Connections.csv`.
Real header confirmed: `CONVERSATION ID, CONVERSATION TITLE, FROM, SENDER
PROFILE URL, TO, RECIPIENT PROFILE URLS, DATE, SUBJECT, CONTENT, FOLDER,
ATTACHMENTS`. `export_sync.py` now uses `SENDER`/`RECIPIENT PROFILE URL`
(not display names) to identify people — more robust, no name-collision
risk. Full pipeline run against the real 1,464-row file: 1,433 became
envelopes, 680/753 outbound/inbound split, 304 threads, 234 identities,
2,871 `message_participant` edges, idempotent on re-run.

**Bug this caught:** the zip also contains
`learning_role_play_messages.csv`, `learning_coach_messages.csv`, and
`guide_messages.csv` — all end in "messages.csv" too, and
`learning_role_play_messages.csv` sorts before the real one in the
archive listing. The original `_parse_messages_csv` matched on
`endswith("messages.csv")` and would have silently parsed the wrong file.
Fixed to match the exact filename.

## LinkedIn: real-time push (parked 2026-08-21 — deprioritised, not abandoned)

The messaging page doesn't poll — it holds open a Server-Sent-Events
connection (`GET /realtime/connect`, kept alive via
`realtimeFrontendClientConnectivityTracking?action=sendHeartbeat`) and
subscribes to specific topics via `PUT realtimeFrontendSubscriptions`
(confirmed live 2026-08-19). This is the same shape as WhatsApp's
persistent-socket approach — hold the connection open and let LinkedIn
push, rather than repeatedly asking "anything new?" — and unlike a polling
loop, it doesn't fight §13's human-paced rule, because it's exactly what a
normal logged-in tab left open does.

**Not implemented yet, on purpose.** The only topic captured so far is
`presenceStatusTopic` (online/offline status) — no new message arrived
during capture, so the topic format for an actual incoming message push is
still unknown. Writing the subscription code before seeing a real one
means guessing the topic URN shape, which is exactly the kind of
unverified assumption this file has been trying to avoid making silently.

**Attempted capture 2026-08-21:** had a contact send a real test message
while watching network traffic on an open `/messaging/` tab. Still only
saw `presenceStatusTopic` subscriptions — the message push itself never
showed up as a new row. Reason: `/realtime/connect` is a single long-lived
SSE connection, and the message arrives as a data chunk streamed through
that *already-open* connection, not as a new discrete HTTP request.
Chrome's Network-domain request list (what this session's tooling reads)
only reports request/response metadata, not the body of an in-flight
streaming response — so there was nothing to see in principle, not a
missed capture.

**Decision: parked, not abandoned.** Data export (backfill) + the
network-interception scraper (backup) already cover this channel end to
end. Seeing the actual push payload would need either instrumenting the
page's own `EventSource`/stream reader from inside the page context
(`page.expose_function`, per the plan below) or a lower-level proxy that
captures streaming response bodies — more investment than justified while
two working paths already exist. Revisit if either of those paths turns
out to be insufficient.

**If picked back up, the plan is still:**
1. Keep a Playwright page open on `/messaging/`.
2. Inject an `EventSource` in-page (same-origin, cookie-authenticated) and
   wire its `onmessage` to a Python callback via `page.expose_function` —
   Playwright's high-level API doesn't stream response bodies chunk-by-
   chunk, so consuming SSE has to happen from inside the page, not by
   listening to `page.on("response")`.
3. On each event matching the real message-topic pattern, parse and
   upsert immediately.

## LinkedIn: backup scraping path

Session expires periodically (LinkedIn logs out idle sessions) — re-run
`login.py` when `sync.py` starts failing to find the conversation list.
Only reach for this if the export path turns out unworkable (too slow,
missing fields once real data lands) — see README for why it's not the
default.

## CI failure on the first push (2026-08-21) — fixed before commit two

`ruff check .` failed with 32 errors, all real, none false alarms:

- Every `# noqa: T201` comment in the repo (added on the assumption
  ruff's default rule set flags bare `print()`) was itself flagged as
  unused — `T201` was never actually enabled in `pyproject.toml`, so the
  noqa comments were dead weight. Removed with `ruff check --fix`.
- `adapters/linkedin/config.py`: `os.environ.get(key, 3.0)` passes a
  float default where the function is typed to return `str | None` —
  worked by accident (`float()`/`int()` are permissive), fixed to pass
  string defaults (`"3.0"`) instead.
- Two nested `with` statements (`scripts/pipe_health.py`,
  `adapters/whatsapp/sync.py`) combined into one per ruff's SIM117.
- `adapters/outlook/client.py`: `for msg in data.get(...): yield msg` →
  `yield from data.get(...)`.
- `adapters/linkedin/export_sync.py`: dropped the manual
  `.replace("Z", "+00:00")` before `fromisoformat()` — Python 3.11+
  accepts a trailing "Z" natively, the workaround predated realising
  that.
- A genuinely deliberate broad `except Exception` in
  `adapters/linkedin/client.py` (a page's own background network traffic
  can fail in any shape) kept its catch, with a `# noqa: BLE001` and a
  reason this time — since `T201`'s lesson was "an unexplained noqa is
  worse than useful," not "never noqa."

**Found in the process, unrelated to the lint failure itself:**
`scripts/pipe_health.py` and `scripts/export.py` both read
`os.environ["DATABASE_URL"]` directly without ever calling
`load_dotenv()` first — meaning neither script had actually been run
end-to-end against a real `.env` file before today; both silently
depended on the variable already being in the shell's environment.
Fixed. `export.py` originally shelled out to a host-installed `pg_dump`
— confirmed broken for real on 2026-08-27/28 via the fresh-deploy
checkpoint below: a genuinely clean machine has no `pg_dump` on PATH at
all, so this failed outright, not just "untested." Rewrote it to run
`pg_dump` inside a throwaway `postgres:16` container instead (see
"Pipeline health monitoring" section's neighbour, the fresh-deploy
checkpoint writeup, for the full verification).

## Pipeline health monitoring

`scripts/monitor.py` (2026-08-27) replaces the old `pipe_health.py`
single-check heartbeat with a per-channel staleness check and a real
alert, meant to run on a schedule instead of by hand:

- **Outlook / LinkedIn** run as one-shot sync scripts, not long-lived
  processes, so their only available signal is "did the last sync run
  recently and write something" — approximated by `max(message.ingested_at)`
  per channel. Thresholds default to 24h (Outlook) / 48h (LinkedIn),
  overridable via `MONITOR_OUTLOOK_STALE_HOURS` /
  `MONITOR_LINKEDIN_STALE_HOURS`.
- **WhatsApp** is a long-running connector (`ingest.js`), where message
  volume alone can't distinguish "the socket died" from "nobody happened
  to message for a while." `ingest.js` now writes its own liveness
  heartbeat to `adapters/whatsapp/node/.heartbeat.txt` every 60s (and
  immediately on connect); the monitor checks that file's mtime instead,
  threshold 5 minutes.
- Alerts always print to stderr; if `MONITOR_ALERT_WEBHOOK_URL` is set
  (a Slack incoming-webhook URL, or anything else that accepts the same
  `{"text": ...}` POST shape), they also get posted there. A failed
  webhook delivery is caught and logged, not fatal to the check itself.
- A per-channel alert only fires once per 6 hours (state in
  `scripts/.monitor_alert_state.json`, gitignored) so a scheduled run
  every few minutes doesn't spam — the channel still shows FAIL on every
  run, it just doesn't re-page.
- Exit code 0 if every channel is healthy, 1 otherwise, so this composes
  with any scheduler without needing anything smarter than "did it exit
  non-zero."

**Verified against the real store and a real `ingest.js` run
(2026-08-27):** with nothing synced in days (Outlook 86.5h, LinkedIn
150.4h) and no heartbeat file yet, all three correctly reported FAIL with
an alert. Starting `ingest.js` flipped WhatsApp to OK within the same
run, heartbeat age 0.2m. Re-running within the cooldown window correctly
suppressed duplicate alerts for the still-failing channels while still
showing their FAIL status. A broken webhook URL was caught and logged
without crashing the check.

**Scheduling this (local dev, until Postgres/hosting migration):**
Windows Task Scheduler, run every 15 minutes:
```
schtasks /create /tn "CommsPlatformMonitor" /tr "\"<path to .venv>\python.exe\" \"<repo path>\scripts\monitor.py\"" /sc minute /mo 15
```
Once the store moves to a real hosted instance, this becomes a proper
cron job / systemd timer next to it instead of a per-laptop scheduled
task.

**Known gap:** nothing schedules the Outlook/LinkedIn/WhatsApp sync
scripts themselves yet — they still run by hand. Until that exists, this
monitor will correctly report Outlook/LinkedIn as stale whenever nobody's
run a manual sync recently, because that's honestly what's happening.
Wiring up the sync schedule itself is separate work from building the
thing that watches it.

**Cost estimate for closing that gap (real scheduled syncs, not just
monitoring them):** roughly 3-4 hours — a Windows Task Scheduler entry
(or cron/systemd timer once hosted) per sync script, each already
idempotent so re-running on a fixed interval is safe as-is; the bulk of
the time is picking sane intervals per channel and confirming a failed
run doesn't corrupt the delta-link/queue state it left mid-write.

## Known gaps at the end of Block A

- Quoted-reply-chain stripping in `envelope.py::_strip_html` is not
  implemented — plain-text body currently includes quoted history. §6
  calls for stripping it; needed clean for both extraction and the voice
  corpus later (Block E), not blocking for Block A itself.
- No polling schedule wired up yet for delta sync — `sync.py` runs once
  per invocation. Cadence is an open question for Mark (not yet decided).
- Contacts ingest (the `/me/contacts` bridge from §8) isn't built —
  identity resolution across channels doesn't start until Block B anyway.
- **LinkedIn rate/volume limits are placeholders, not agreed numbers.**
  §13 rule 2 requires Mark's written sign-off before these change —
  `adapters/linkedin/config.py` ships a conservative guess (3–8s between
  actions, 20 pages/session, 4 sessions/day) so the adapter has something
  to run with, but don't treat these as decided.
- **LinkedIn message id/timestamp: fixed in design, unverified in practice.**
  Rebuilt `client.py` to read the `voyagerMessagingGraphQL` JSON responses
  the page itself fetches (via Playwright's `page.on("response")`) instead
  of scraping rendered text — those responses carry a stable `entityUrn`
  and a real epoch timestamp per message. But the exact field names in
  `_extract_messages()` (`eventContent.attributedBody.text`, `createdAt`,
  etc.) were inferred from LinkedIn's documented RestLi conventions, not
  confirmed against a live response — the manual probe that would have
  confirmed it was correctly blocked by Claude Code's safety classifier
  (constructing an authenticated request with an extracted CSRF token,
  outside of normal Playwright page control, reads as exactly the kind of
  action that guardrail exists to catch). **First real run against
  `login.py` + `sync.py` needs to happen with someone watching, to confirm
  the field names actually match and fix them if not.**
- **Virtualized-list scrolling: implemented, unverified.** Both the
  conversation list and each thread's message history only render what's
  scrolled into view. `_collect_conversation_hrefs` and
  `_scroll_thread_history` in `client.py` now scroll-and-recheck until
  nothing new shows up (bounded by `max_scroll_attempts`), instead of only
  reading the first screenful — but like the response field names above,
  this hasn't been run against a real long history yet.
- The conversation-list link discovery now keys off
  `a[href*="/messaging/thread/"]` — LinkedIn's URL routing, not a CSS
  class — specifically because routing is more durable than styling. The
  scroll *containers* themselves (`ul.msg-conversations-container__conversations-list`,
  `.msg-s-message-list`) are still class-selected and captured live on
  2026-08-19; those will still need periodic re-capture.

### Found and fixed while self-reviewing this file (2026-08-19)

- **Direction was always wrong.** `LINKEDIN_MEMBER_ID` is documented as
  the bare id from a profile URL; every id pulled from the JSON responses
  is a full `urn:li:fsd_profile:<id>` URN. Comparing the two formats
  directly meant `direction` could never resolve to outbound — every
  message you'd ever sent would have landed in the store as if someone
  else sent it to you, corrupting exactly the `message_participant` edges
  the network graph depends on. Fixed with `_to_profile_urn()`, which
  normalises both sides before comparing.
- **Messages could get attributed to the wrong thread.** `captured` is
  cleared right before navigating to the next conversation, but a slow
  network response from the *previous* thread landing after that clear
  would get tagged with the *new* thread's id. Each message's payload
  already carries a `conversation_urn` — it just wasn't being checked.
  Now it is, before a message is yielded.
- **A crash partway through lost everything already scraped.** `sync.py`
  used to collect every envelope into a list before opening a database
  connection at all. `client.run()` is now a generator and `sync.py`
  upserts + commits each message as it arrives, so a failure on
  conversation 40 of 50 keeps the first 39.

### Still open, not yet fixed

- Both scroll loops decide "no more history" by sleeping a fixed duration
  and checking whether anything new arrived — a slow response landing just
  after that sleep reads as "nothing more to load" and truncates history.
  The correct fix is `page.expect_response()` around each scroll instead
  of a flat `time.sleep()`.
- The browser launches with Playwright's default headless Chromium
  fingerprint — no custom user agent, no anti-detection handling of any
  kind. For a feature that's explicitly ToS-grey (§13), this is the part
  most likely to get the account flagged, and it's currently the least
  defended.
