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
2. Set `LINKEDIN_SELF_PROFILE_URL` in `.env` to your own profile URL (used
   by the export path to tell your own messages apart from theirs). The
   network-interception path (client.py/sync.py) needs no id configured
   at all — see the entry below on why.

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

**Connections.csv added 2026-08-28** — same archive, a second file,
parsed and upserted into a new `linkedin_connection` table alongside the
messages. This is §8 Rule 5's actual raw material ("name plus
organisation correlation for LinkedIn") — company name, not email, is
the useful field here. Checked against the real archive already sitting
in Downloads from the 2026-08-21 run (reused it rather than requesting
a fresh one and spending another LinkedIn session):

- 935 rows, 890 (95%) carry a company name, only 25 (2.7%) carry an
  email — LinkedIn only includes a connection's email if they opted into
  sharing it (`Email Addresses.csv` in the same archive is *your own*
  saved emails, not connections' — don't confuse the two).
- No `Followers.csv` anywhere in the 34-file archive. LinkedIn's export
  covers connections (mutual), not followers (one-way) — that data isn't
  available through this path at all.
- Parsing quirk: unlike `messages.csv`, `Connections.csv` has a
  three-line preamble (a privacy disclaimer explaining the sparse email
  coverage above) before the real header row — `_parse_connections_csv`
  scans for the header rather than assuming line 1.
- 14 of 935 rows are completely blank (no name, no URL) — deactivated/
  deleted LinkedIn accounts, where LinkedIn keeps the connection date but
  strips every identifying field. All 14 collapse to the same fallback
  id and only the last survives — not real data loss, but the row count
  in the table (922) will legitimately be lower than the CSV's (935).
- Unlike every other Block A source, this can only be a periodic
  snapshot — there's no delta/webhook for "who connected since last
  time," only re-requesting a fresh ~24h archive. Worth deciding a real
  cadence for this (monthly? on demand?) rather than treating it like
  the continuously-synced channels.
- **Not yet run through `run()`'s actual download step this session** —
  tested `_parse_connections_csv`/`_sync_connections` directly against
  the already-downloaded archive to avoid opening another LinkedIn
  browser session on top of everything else scraped today. The download
  half of the flow was already verified separately on 2026-08-21;
  worth a real end-to-end run once a fresh archive is warranted anyway.

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

**Outlook sync scheduling — done 2026-08-28, cadence bumped 2026-08-30.**
Mark approved a 15-minute cadence on the 2026-08-28 call, then tightened
it to 10 minutes in his written follow-up the same week.
`scripts/run_outlook_sync.bat` `cd`s into the repo before invoking the
venv's `python -m adapters.outlook.sync` — needed because `load_dotenv()`
in `sync.py` resolves `.env` relative to the process's working directory,
not the script's own location, and Task Scheduler does not otherwise set
a working directory; confirmed empirically (`find_dotenv()` returned
nothing when launched from outside the repo). Registered as a real
Windows Task Scheduler task, then re-pointed at the 10-minute interval:
```
schtasks /create /tn "CommsPlatformOutlookSync" /tr "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_outlook_sync.bat" /sc minute /mo 10 /st 00:00
```
**⚠ This exact command is broken — see "Found broken, fixed for real"
below. Don't copy it; use the `Register-ScheduledTask` version there.**
Verified live: ran the batch file by hand first (synced 3 messages, `.env`
loaded correctly from the repo root), confirmed the registered task
itself via `schtasks /query /tn "CommsPlatformOutlookSync" /v` at the
original 15-minute interval, then changed it in place
(`schtasks /change /tn "CommsPlatformOutlookSync" /ri 10`) and re-queried
to confirm `Repeat: Every: 10 Minute(s)`. **This verification itself
turned out to be insufficient — `/query`'s display masked the real bug;
see below.**

**LinkedIn sync scheduling — done 2026-08-30.** Mark's cadence call
specified 4 sessions/day at fixed clock times, ~9am/12:30/3:30/7pm, with
jitter — a flat interval doesn't fit here the way it does Outlook, both
because of the timetable and because `max_sessions_per_day=4` (§13 rule
2, a fixed rate/volume param) would reject a 5th run anyway.
`scripts/run_linkedin_sync.py` sleeps a random 0-15 minute jitter
(`RateLimits.session_jitter_minutes`, tunable via
`LINKEDIN_SESSION_JITTER_MINUTES` — this one isn't a §13 rule 2 param, it
only affects when a session *starts*, not how it behaves once running,
so no sign-off needed to tune it) before calling
`adapters.linkedin.sync.run()`. Verified the jitter/call wiring with the
real `sync.run` swapped for a stub — confirmed it actually gets called
after the sleep — without spending a real session on a wiring test.
Registered as four separate Windows Task Scheduler tasks, one per time
slot, each pointing at `scripts/run_linkedin_sync.bat` (same
`cd`-into-repo-first pattern as Outlook's wrapper, same reason):
```
schtasks /create /tn "CommsPlatformLinkedInSync-0900" /tr "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_linkedin_sync.bat" /sc daily /st 09:00
schtasks /create /tn "CommsPlatformLinkedInSync-1230" /tr "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_linkedin_sync.bat" /sc daily /st 12:30
schtasks /create /tn "CommsPlatformLinkedInSync-1530" /tr "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_linkedin_sync.bat" /sc daily /st 15:30
schtasks /create /tn "CommsPlatformLinkedInSync-1900" /tr "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_linkedin_sync.bat" /sc daily /st 19:00
```
**⚠ Also broken, same reason — see "Found broken, fixed for real"
below.**
Verified all four live via `schtasks /query ... /v`: correct `Task To
Run` path, `Status: Ready`, and each `Next Run Time` landing on its own
slot. **This check was also insufficient — see below.**

**Still open:** WhatsApp is not on a schedule — it's the long-running
`ingest.js` connector rather than a one-shot sync, so it needs to run
continuously on Mark's cloud box rather than on a Task Scheduler trigger,
blocked until that box exists.

**Found broken, fixed for real — 2026-08-31.** All five tasks above had
never actually run successfully since creation. `schtasks /create /tr`
with a quoted path containing a space ("Eva Ng") got silently split by
Task Scheduler into `Execute=C:\Users\Eva` +
`Arguments=Ng\...\run_outlook_sync.bat` — `schtasks /query ... /v`'s
"Task To Run" field shows the reconstructed string, which looked correct
and masked this; `Get-ScheduledTask | Select Actions` shows the real
Execute/Arguments split and was what actually caught it. Every run that
had fired failed with result `-2147024703`
(`ERROR_MOD_NOT_FOUND`) — three days of "scheduled" Outlook/LinkedIn
sync that never happened, only caught by actually running
`scripts/monitor.py` and seeing all three channels flagged unhealthy
rather than trusting the earlier `schtasks /query` check. Recreated all
five via PowerShell's `Register-ScheduledTask`/`New-ScheduledTaskAction`
instead of `schtasks.exe`'s CLI string parsing, confirmed each one's
`Actions.Execute` is the full clean path with empty `Arguments`.
Verified live: triggered Outlook manually, `LastTaskResult: 0`, and a
new row landed in the store with `ingested_at` matching the trigger
time — not just "the process exited 0," the sync actually happened.
Triggered one LinkedIn slot the same way to confirm the fix holds there
too. The actual working recipe, for recreating any of these:
```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_outlook_sync.bat"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "CommsPlatformOutlookSync" -Action $action -Trigger $trigger -Force
```
(`-RepetitionDuration ([TimeSpan]::MaxValue)` fails outright — Task
Scheduler rejects the resulting ISO 8601 duration as out of range; a
long finite duration like 10 years works.)

**Found broken #2, same day — task LogonType, not yet fixed.** Every
task above registers with `Principal.LogonType = Interactive` by
default, meaning it only fires while the account is actually logged in
(locked is fine, logged out is not) — a real problem for "unattended"
given a laptop that gets logged out or restarted without auto-login.
The fix is `-LogonType S4U` (runs on schedule regardless of logged-in
state, no stored password needed), but `Set-ScheduledTask` requires an
elevated PowerShell session this one didn't have — confirmed by trying
it and getting `Access is denied`, not by assuming. Left as a real open
item, not silently worked around:
```powershell
$tasks = @("CommsPlatformOutlookSync","CommsPlatformLinkedInSync-0900","CommsPlatformLinkedInSync-1230","CommsPlatformLinkedInSync-1530","CommsPlatformLinkedInSync-1900","CommsPlatformMonitor")
foreach ($t in $tasks) {
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
  Set-ScheduledTask -TaskName $t -Principal $principal
}
```
Run from an elevated PowerShell to actually close this gap.

**`scripts/monitor.py` itself, actually scheduled — 2026-08-31.** Same
gap as above, one level up: the monitor that's supposed to catch a dead
channel had never been scheduled either, so the three days of broken
Outlook/LinkedIn tasks above went unnoticed until it was run by hand.
Registered as `CommsPlatformMonitor`, same `Register-ScheduledTask`
pattern, every 15 minutes. Verified: triggered manually,
`LastTaskResult: 0`.

**Real alerting — ntfy.sh, 2026-08-31.** `MONITOR_ALERT_WEBHOOK_URL` had
existed since the first version of `monitor.py` but was never set to
anything, so every alert before today only ever reached a stderr stream
nobody was watching. `_send_alert` now also posts to `MONITOR_NTFY_TOPIC`
on ntfy.sh — free, no account, subscribed on phone and desktop via the
topic URL, the topic name itself treated as a shared secret (long random
string, not guessable). Verified live: sent two real test alerts,
confirmed delivered.

**WhatsApp: "is it a zombie" is now an answerable question, not a
guess — 2026-08-31.** Prompted directly by "how do we even tell if it's
a zombie or a live one, and what do we do about it." Before this,
`ingest.js` only ever wrote a heartbeat file and printed to a console
that vanishes when the terminal closes — a stale heartbeat couldn't tell
you *why*, and nothing distinguished "process crashed and exited" from
"process alive but stuck" from "session got logged out and needs a
fresh QR scan." Added:
- `.status.json` — current state (`connected` / `reconnecting` /
  `logged_out` / `qr_pending` / `crashed`), written on every connection
  transition.
- `.pid` — written once at process start, so a caller can check whether
  the OS process is actually still running, independent of the
  heartbeat.
- `.connection_log.txt` — persistent, timestamped event log (connects,
  disconnects with reason code, QR generation, fatal errors), so a
  future incident has real evidence instead of nothing. `uncaughtException`
  / `unhandledRejection` handlers now log the crash here before exiting
  with the same code Node's default handler would have used — previously
  these left zero trace anywhere once the terminal closed.
- Also fixed a real, separate bug found while doing this: the logged-out
  message told you to "re-pair via login.js" — no such file exists in
  this repo; pairing happens by deleting `.auth_state` and re-running
  `ingest.js` itself, which generates a fresh QR. Fixed the message to
  say the actual command.

`monitor.py`'s WhatsApp check now reads `.status.json` and `.pid`
instead of only the heartbeat's age, and classifies into the states that
actually matter, each with the literal next command:
- `logged_out` → delete `.auth_state`, rerun `ingest.js`, scan the new QR
- `qr_pending` → open `qr.png`, scan it
- `crashed` → restart `ingest.js`, check `.connection_log.txt` if it
  recurs
- stale heartbeat + pid confirmed still running (via `tasklist`) →
  **ZOMBIE** — `taskkill /PID <pid> /F` then restart
- stale heartbeat + pid gone → **DOWN** — just restart

**Verified all three states for real, not just read the code:** faked a
stale heartbeat with the `.pid` pointing at this shell's own real PID →
correctly reported `ZOMBIE` with the exact `taskkill` command; pointed
it at a nonexistent PID → correctly reported `DOWN`; set
`.status.json` to `logged_out` → correctly reported the QR re-pair
steps. Restored the real files afterward and re-ran `monitor.py`
against the actual live connector — back to `OK`, heartbeat 0.1m old,
confirming the test didn't leave anything broken.

**What caused the original 2026-08-27 zombie is still genuinely
unknown** — there was no persisted log at the time, only console output
that's gone once that terminal closed, so nothing above should be read
as having found that root cause. What changed is that the same failure
now leaves evidence: `.connection_log.txt` and the `uncaughtException`/
`unhandledRejection` handlers exist specifically so the next one doesn't
end the same way.

## Known gaps at the end of Block A

- **Quoted-reply-chain stripping — done 2026-08-28.** `_strip_html` in
  `adapters/outlook/sync.py` now cuts the body at the first quote marker
  found. Checked against this mailbox's real data before picking which
  markers matter: Outlook's own `divRplyFwdMsg` appeared in only 0.7% of
  messages here (this mailbox is Gmail-seeded test data), so `gmail_quote`
  (7.2%) and bare `<blockquote>` (8.2%, catches other clients) are the
  ones that actually count. First version matched `class="gmail_quote"`
  exactly and silently missed 25 of 27 real cases — real markup pairs it
  with a second class (`class="gmail_quote gmail_quote_container"`) or
  prefixes it (`class="x_gmail_quote"`); fixed to match the substring
  anywhere inside the class attribute instead. Verified: 423/425 real
  messages with a quote marker got shorter after stripping (the other 2
  matched too, just at a position with nothing meaningful left to cut).
  A plain-text fallback (`"On ... wrote:"`) covers the 103 of 4,769
  messages here that aren't HTML at all.
- No polling schedule wired up yet for delta sync — `sync.py` runs once
  per invocation. Cadence is an open question for Mark (not yet decided).
- **`is_automated` now set from a real signal, 2026-08-28.** §9 tier 1's
  own table names this exact one: "Graph's own Focused/Other
  classification. Sets `is_automated` at ingest." Added
  `inferenceClassification` to the Graph `$select` and map `"other"` to
  `true`. This is one field, not tier 1's full ruleset (List-Unsubscribe
  header, known automated domains, bulk-sender patterns are still real
  Block B work) — and tier 1 itself is Block B scope per §14's own table,
  so treat this as a deliberate small exception, not tier 1 quietly
  starting early. Verified against 10 real messages (8 focused / 2 other,
  mapped correctly), then backfilled the 4,772 already-ingested messages
  that predate this field existing in the raw payload — `store_writer`'s
  upsert is on-conflict-do-nothing, so a normal re-sync would never have
  touched them otherwise. 2,177 of 4,772 (46%) came back classified
  "other."
- **LinkedIn rate/volume limits are placeholders, not agreed numbers.**
  §13 rule 2 requires Mark's written sign-off before these change —
  `adapters/linkedin/config.py` ships a conservative guess (3–8s between
  actions, 20 pages/session, 4 sessions/day) so the adapter has something
  to run with, but don't treat these as decided.
- The scroll *containers* (`ul.msg-conversations-container__conversations-list`,
  `.msg-s-message-list`) are still class-selected and captured live on
  2026-08-19/28; those will still need periodic re-capture if LinkedIn
  reworks the page again.

### LinkedIn network-interception path — verified for real, 2026-08-28

Everything below was previously "fixed in design, unverified in
practice" — the response field names were guessed from LinkedIn's
documented RestLi conventions, never confirmed against a live message.
Verified this session by sending a real message from a second (throwaway)
LinkedIn account to the real one and capturing what actually came back.
The guess was wrong in three separate places, all now fixed:

1. **Response shape.** No `included` array at all — real shape is
   `data.messengerMessagesBySyncToken.elements[]`, each element a Message
   object directly. Text is at `body.text`, sender id at
   `sender.hostIdentityUrn`. `_extract_messages()` rewritten accordingly.
2. **"Who am I."** `LINKEDIN_MEMBER_ID` was meant to hold your profile's
   internal id, but the documented way to find it (the vanity slug from
   your own profile URL, e.g. "evang2") isn't that id at all — it never
   matched anything pulled from a real response, so direction was always
   wrong. Fixed by removing the env var entirely: every
   `conversation.entityUrn` LinkedIn sends already embeds your own real
   profile urn as its first component
   (`urn:li:msg_conversation:(<your urn>,<thread id>)`), so
   `_self_urn_from_conversation_urn()` derives it per-message instead of
   trusting a separately-configured value that could drift out of sync.
3. **Conversation list navigation.** The old code assumed conversation
   rows were `<a href="/messaging/thread/...">` links and navigated by
   URL — real DOM has no such links at all; LinkedIn routes client-side
   off a click handler on a plain `<div class="msg-conversation-listitem__link">`.
   Rewritten to click each row by position instead of navigating by href;
   which thread a batch of captured messages belongs to is now
   ground-truthed from the response payload's own `conversation.entityUrn`
   rather than guessed from how the (nonexistent) href was encoded.

**Verified against real data:** full sync against the real inbox synced
122 messages (740 outbound / 814 inbound — a plausible split, unlike the
old code which could never produce outbound at all). Re-ran immediately
after: store row count unchanged (1554 before and after), confirming
`on conflict do nothing` idempotency holds for this path too. Virtualized
conversation-list scrolling was exercised for real reaching the
`max_pages_per_session` cap (20), not just implemented-but-untested.

**One resilience fix made along the way, not a bug in the above:** some
conversation rows (a bare connection-request preview, LinkedIn's own
automated threads) don't render a normal message-list DOM at all —
clicking them used to hang the whole run waiting on a selector that would
never appear. `fetch_conversations` now catches that specific timeout and
skips just that row.

### Found and fixed while self-reviewing this file (2026-08-19)

- **Direction was always wrong.** `LINKEDIN_MEMBER_ID` is documented as
  the bare id from a profile URL; every id pulled from the JSON responses
  is a full `urn:li:fsd_profile:<id>` URN. Comparing the two formats
  directly meant `direction` could never resolve to outbound — every
  message you'd ever sent would have landed in the store as if someone
  else sent it to you, corrupting exactly the `message_participant` edges
  the network graph depends on. Fixed at the time with `_to_profile_urn()`,
  which normalised both sides before comparing — **this fix turned out to
  be incomplete, not wrong in principle but built on a wrong assumption**:
  the profile-URL vanity slug (e.g. "evang2") normalised into
  `_to_profile_urn()` was never the right id to begin with, confirmed
  2026-08-28 against a real message. `_to_profile_urn()` and
  `LINKEDIN_MEMBER_ID` are both gone now — see the 2026-08-28 section
  above for what replaced them.
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
- **Anti-detection posture — decided 2026-08-28, not a gap.** All four
  LinkedIn browser launches go through `adapters/linkedin/browser.py`'s
  `launch_browser_context()`, which uses the real, locally-installed
  Chrome (`channel="chrome"`) and a realistic viewport, and does nothing
  else — no `navigator.webdriver`/`plugins` patching, no User-Agent
  rewriting. An earlier version of this file did both, built off a
  verbal "make it more human" approval on a call; Mark's written
  follow-up the same day ratified the opposite: no fingerprint or
  countermeasure work, ever, pacing and the §13 daily session cap ARE
  the strategy, and if that stops being sufficient the response is to
  stop and talk, not escalate technique. Reverted the JS patches and UA
  rewrite accordingly; kept `channel="chrome"` since it doesn't falsify
  anything the browser reports, it's just which real browser runs.
