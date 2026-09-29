---
name: deploy-comms-platform
description: Deploy a fresh Ironman instance, upgrade an existing instance, or install the local Network trial on an existing Mac or Windows setup.
---

# Deploy: Comms & Outreach Platform

## Existing instance: Network trial

For the real-data Network trial on an already working Ironman, follow
[`docs/demos/network-trial-upgrade.md`](../../../docs/demos/network-trial-upgrade.md)
from the repository root. This is the Mac/Windows upgrade branch of this skill.
Run its source audit, derived-schema check, separate worker/app startup and
read-only acceptance check. Keep the existing collectors, credentials and Inbox
running. The trial uses the operator's existing source and its own `network`
schema; it does not require source migrations, channel reauthentication or Docker.

Use the release revision named in the delivery record. Report Windows, clean
checkout and target-Mac checks separately; preparation is not Mac validation.
An authorized autonomous deployment remains authorized across routine steps;
ask only when the next operation exceeds that scope or a system permission
requires it. A failed check stops that deployment stage, with the old service
still usable.

For other upgrades or fresh deployments, continue below.

Operationalizes `runbook.md` into a step-by-step walkthrough with a real
verification check after each step — not "run this command and hope,"
but "run this command, then run this OTHER command to confirm it
actually worked, and here's what to do if it didn't."

**Read `runbook.md` first if a step below is unclear or fails in a way
this file doesn't cover** — it has the full narrative history (including
several real incidents and their root causes) behind every command here;
this file gives you the distilled path.

## Ground rules

- **Never touch real credentials on the operator's behalf.** Every
  `.env` value, every device-code sign-in, every WhatsApp QR scan, every
  LinkedIn login is something the human running this does themselves,
  watching their own screen. Your job is to tell them which command to
  run and which file to check, not to enter anything into a login form.
- **Confirm before every step that mutates state** (writes to `.env`,
  runs a database migration, starts a service) — this deploys real
  infrastructure, not a sandbox. A read-only check (`SELECT`, `systemctl
  status`, `ls`) doesn't need confirmation; anything that changes
  something does.
- **Verify, don't assume.** Every step below ends with a command whose
  output tells you whether it actually worked. If a step "looks like it
  should have worked" but the verification command disagrees, trust the
  verification command — `runbook.md`'s "Found broken, fixed for real"
  section (Windows Task Scheduler silently mis-registering all five
  scheduled tasks despite `schtasks /query` reporting them healthy) is
  exactly the failure mode this rule exists to catch.
- **This machine does NOT need Docker.** Production points at a real
  Supabase project (Mark's own account), not a self-hosted Postgres
  container — Docker/Compose in this repo is only for local dev and the
  test suite, neither of which apply to a production deploy. Don't
  install Docker as part of this unless something below says to.

## Database access: Supabase MCP if available, `psql`/`psycopg` otherwise

Every verification step below that touches the database is phrased as
"check X." How you check is a choice, made once at the start:

1. **Check whether Supabase MCP tools are available** in this session —
   look for tools named `mcp__*supabase*` (e.g. `list_tables`,
   `execute_sql`, `get_advisors`). If present and the operator has
   already connected them to the right project, prefer them: `list_tables`
   / `execute_sql` for the checks below, and run `get_advisors` once near
   the end as a free security/performance sanity check.
2. **Otherwise, use `psql` or Python (`psycopg`) against `DATABASE_URL`
   from `.env`** — every check below has an equivalent `psql`/Python form
   for exactly this reason. This is the default path; don't ask the
   operator to connect Supabase MCP just to make this skill work — it's
   a much bigger trust decision (direct read/write access to their
   production database) than they should be asked to make mid-deploy,
   and everything here works fine without it.

Never assume one is available — check at the start of this run, once,
and use whichever is real.

## Step 0: Detect current state — scan, don't ask

Don't ask the operator whether this is a fresh box or an existing
instance being updated; they may not remember precisely, and this repo
already carries the real signal everywhere it matters. Check directly:

```bash
uname -a; cat /etc/os-release 2>/dev/null   # OS — Linux assumed below;
  # on Windows, runbook.md's "Deploying a clean instance" / scheduling
  # sections apply instead
cd <repo-dir> 2>/dev/null && git rev-parse --is-inside-work-tree 2>/dev/null \
  && echo "existing checkout" || echo "no checkout here — fresh deploy"
```

**If it's an existing checkout**, the directory already tells you
exactly what it's missing — don't guess, diff it against the real
source of truth:

```bash
git fetch origin
git log --oneline HEAD..origin/main
```
This commit list *is* the gap. Read through it (`git log -p` on any
commit touching `db/migrations/`, `pyproject.toml`, or anything else
you're unsure about) before changing anything — it tells you which
migrations, dependencies, and behavior changes this instance doesn't
have yet, the same way the pydantic incident (Step 3's note below)
should have been caught by checking this instead of assuming a `git
pull` alone was enough.

Then gather the rest of the picture the same way — compare reality
against the repo's current expectations, not against what anyone
remembers configuring:
- **`.env` gaps** (a key can be missing outright, not just blank, if it
  postdates this instance's first deploy — `ANTHROPIC_API_KEY` is a
  real example):
  ```bash
  diff <(grep -oE '^[A-Z_]+=' .env.example | sort) <(grep -oE '^[A-Z_]+=' .env | sort)
  ```
  Any line only on the left needs adding — see Step 1's field notes.
- **DB gaps**: run Step 2's table-list verification query now, before
  applying anything, to see which migrations are already in effect —
  there's no migration-tracking table, so the actual schema is the only
  reliable record.
- **Dependency gaps**: `pip install -e .` is cheap and idempotent —
  just re-run it (Step 3) rather than trying to diagnose which specific
  package is missing.
- **Service gaps**: Step 7's `systemctl`/`journalctl` checks show
  whether the running services reflect the code that was just pulled,
  or still need a restart.

Turn what actually came back from these checks into a concrete list —
which commits arrived, which `.env` keys are missing, which migrations
aren't applied, whether services need restarting — and work through
each with the matching step below (Step 1 for env fields, Step 2 for
migrations, Step 3 for deps, Step 7 for restarting services). The steps
below are the "how" for each category of gap; this scan is the
"whether," decided from the real state of this machine, not asked.

**If there's no existing checkout**, this is a fresh deploy — continue
through Step 1 onward in order, as written.

## Step 1: Clone and `.env`

```bash
git clone <repo-url>
cd <repo-dir>
cp .env.example .env
```

Walk the operator through **every** blank field in `.env.example`,
one at a time — don't dump the whole file at them:
- `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` — from their own Entra app
  registration (they need to have created one; this skill doesn't cover
  that setup, only using it)
- `OUTLOOK_MAILBOX` — the mailbox address being connected
- `LINKEDIN_SELF_PROFILE_URL` — their own LinkedIn profile URL
- `DATABASE_URL` — from their Supabase project's connection string
  (Settings → Database → Connection string, "URI" format, **not** the
  pooler's transaction-mode string if migrations need to run — session
  mode or the direct connection string)
- `WHATSAPP_AUTH_ENCRYPTION_KEY` — generate it for them:
  `openssl rand -base64 32`
- `MONITOR_NTFY_TOPIC` — a long random string they pick (this becomes
  their alert channel — subscribe to `https://ntfy.sh/<topic>` on their
  phone once it's set)
- `ANTHROPIC_API_KEY` — their own key from console.anthropic.com, not a
  shared one. Powers `ai_brief` (the per-contact summary/context/urgency
  shown in the `/inbox` triage view) — every channel sync calls into it
  after ingesting, so a blank key doesn't just disable summaries, it logs
  a swallowed exception on every sync run (`refresh_touched_best_effort`
  is deliberately best-effort and never fails the sync itself — see
  adapters/ai_brief.py). `ANTHROPIC_MODEL` is fine to leave blank; the
  code falls back to a default.

**Verify:** `.env` has no blank `=` lines left for the fields above
(`MONITOR_ALERT_WEBHOOK_URL` and the `LINKEDIN_*` rate-limit vars are
fine to leave at their defaults):
```bash
grep -E '^(AZURE_TENANT_ID|AZURE_CLIENT_ID|OUTLOOK_MAILBOX|LINKEDIN_SELF_PROFILE_URL|DATABASE_URL|WHATSAPP_AUTH_ENCRYPTION_KEY|MONITOR_NTFY_TOPIC|ANTHROPIC_API_KEY)=$' .env
```
This should print nothing. If it prints a line, that field is still
blank — go back and fill it before continuing.

## Step 2: Supabase — apply all migrations, in order

**Confirm with the operator first**: this writes schema to their real
Supabase project. Not reversible by this skill (some migrations create
tables; none currently drop anything, but treat it as a one-way door).

There is no migration-tracking table in this schema — nothing records
which files have already run against a given database. That's fine for
a fresh database (every file is new), but **on an already-deployed
instance being updated, re-running an already-applied `create table`
migration errors** (no `if not exists` in these files) — safe to ignore
that specific error and move to the next file, since it just means this
one was already applied; anything else is a real failure and should
stop the run. Use the Python form below for updates (it distinguishes
the two); the plain `psql` loop is fine for a first-time/fresh deploy
where every file is guaranteed new:

```bash
for f in db/migrations/*.sql; do
  echo "applying $f"
  psql "$DATABASE_URL" -f "$f" || { echo "FAILED at $f — stop here"; break; }
done
```
Idempotency-safe form (works for both a fresh deploy and an update —
prefer this one if unsure, or if `psql` isn't installed):
```bash
python3 -c "
import glob, os
import psycopg
from psycopg.errors import DuplicateTable, DuplicateObject, DuplicateColumn

dsn = os.environ.get('DATABASE_URL') or open('.env').read()  # prefer an exported env var
for f in sorted(glob.glob('db/migrations/*.sql')):
    try:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(open(f).read())
            conn.commit()
        print('applied', f)
    except (DuplicateTable, DuplicateObject, DuplicateColumn) as e:
        print('already applied, skipping', f, '-', e)
"
```
— but load `DATABASE_URL` from `.env` properly first, e.g. `export
$(grep DATABASE_URL .env)` before running this. Any other exception
(not one of the three caught above) is a real failure — stop and read
the actual error rather than assuming it's another "already applied"
case.

**Verify — all base tables + views exist:**
```sql
select table_name from information_schema.tables where table_schema = 'public' order by 1;
```
Expect: `action, ai_brief, contact_graph_strength, contact_hidden,
contact_last_message, contact_reciprocity, contact_stats, event, fact,
graph_contact, identity, link_candidate, linkedin_connection, merge_log,
message, message_participant, organization, outreach, person, thread`
(20 names as of migration 0009 — re-run `ls db/migrations/` and
`grep -h '^create table\|^create.*view' db/migrations/*.sql` to
regenerate this list if migrations have been added since this skill was
last updated; the count should track 1:1-ish with what the migrations
create).

If a migration fails partway: read the actual error (don't guess) —
common causes are running an later migration before an earlier one
(foreign key to a table that doesn't exist yet — this is why the loop
above stops on first failure instead of ignoring it and continuing) and
a stale/wrong `DATABASE_URL` (double check it's pointed at the intended
project, not a leftover local one from `.env.example`'s default).

## Step 3: Python environment

```bash
python3 --version   # need 3.11+
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Verify:**
```bash
python3 -c "import adapters.envelope; print('ok')"
```
Should print `ok` with no import errors.

**If this is an update to an already-deployed instance (`git pull` on an
existing checkout, not a fresh clone), always re-run `pip install -e .`
after pulling — even if the pulled commits "don't look dependency
related."** A real incident: a new `pydantic` dependency was added to
`pyproject.toml` alongside an `ai_brief.py` change, tested successfully
in a separate dev session, but never installed into the actual `.venv`
the deployed scheduled tasks/services use. Every channel's sync crashed
at import time for ~2 days before anyone noticed, because Outlook,
WhatsApp, and LinkedIn sync all import `ai_brief` at module load —
one missing dependency broke all three, not just the feature that
needed it. Verify after every update, not just the first deploy:
```bash
python3 -c "import adapters.outlook.sync, adapters.whatsapp.sync, adapters.linkedin.sync; print('ok')"
```

## Step 4: Connect Outlook

```bash
python -m adapters.outlook.sync
```
First run triggers a device-code prompt — the operator opens the printed
URL themselves, enters the code, signs in as `OUTLOOK_MAILBOX` on their
own screen. Don't attempt to automate or observe this login.

**Verify:**
```bash
python scripts/pipe_health.py
```
Expect `OK: last ingest at <timestamp>`. `UNHEALTHY: store is reachable
but empty` means auth succeeded but nothing synced yet — re-run the sync
once; if still empty after a real sync attempt, check the mailbox
actually has mail Graph can see (Focused/Other, not just a specific
folder Graph's default query might miss).

## Step 5: Connect WhatsApp

```bash
cd adapters/whatsapp/node && npm install
node ingest.js
```
Prints a QR to the console and writes `qr.png` — operator scans it from
their own phone (WhatsApp → Settings → Linked devices → Link a device).
Leave it running (or move to Step 7's systemd service once that's set
up) rather than closing the terminal.

**Verify**, in a second terminal:
```bash
cat adapters/whatsapp/node/.status.json
```
Expect `"state": "connected"` (or absent `state` with a fresh
`.heartbeat.txt` — both mean it's live). `qr_pending` means the scan
hasn't landed yet; `logged_out` means delete `.auth_state` and restart
`ingest.js` for a fresh QR.

Then drain the queue into the store:
```bash
python -m adapters.whatsapp.sync
```
**Verify:** `python scripts/pipe_health.py` again — last ingest time
should have moved forward if there were any queued messages.

## Step 6: Connect LinkedIn

Two parts — see `runbook.md`'s "LinkedIn: first-time setup" and
"LinkedIn: the data-export sync" sections for the full detail; summary:

1. Browser login (`adapters/linkedin/login.py` or via the ops dashboard,
   Step 7) — operator logs in on their own screen, session gets saved
   to `.storage_state.json`.
2. Request their data export from LinkedIn directly (Settings & Privacy
   → Data privacy → Get a copy of your data) — **this has up to a ~24h
   turnaround**, not something this skill can wait on. Once the archive
   email arrives, download it and point the export sync at it per
   `runbook.md`'s instructions.

**Verify (after the export sync runs):**
```sql
select count(*) from identity where channel = 'linkedin';
```
via whichever DB access path Step "Database access" above resolved to.
Expect a nonzero count.

**A real, known gap for a headless Linux box**: LinkedIn's browser path
uses real Google Chrome (`channel="chrome"` in Playwright), not the
Chromium Playwright bundles — a headless Linux server needs Chrome
installed separately (`playwright install chrome` still requires the
system to have what Chrome itself needs; a truly headless box may need
`xvfb` or Chrome's own headless flags depending on how `adapters/linkedin/browser.py`
launches it). **Test this on the actual target box before relying on
it** — this has not been verified on Linux as of this skill being
written.

## Step 7: Long-running services (systemd)

See `runbook.md`'s "Linux deployment: scheduling and long-running
services" section for the actual unit files (Outlook/LinkedIn timers,
WhatsApp + dashboard `Restart=always` services) — copy them in, adjust
the path if the checkout isn't at `/opt/comms-platform`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now comms-outlook-sync.timer comms-linkedin-sync.timer comms-whatsapp.service comms-dashboard.service
```

**Verify each one actually ran, not just that it's registered** — this
is the single most important lesson from the Windows side of this
runbook (a task can look perfectly registered and never have actually
fired):
```bash
systemctl list-timers comms-outlook-sync.timer comms-linkedin-sync.timer
journalctl -u comms-outlook-sync.service -n 20   # did the last run succeed
journalctl -u comms-whatsapp.service -n 20 -f    # tail the live connector
systemctl status comms-dashboard.service
```
Then re-run `python scripts/pipe_health.py` and check
`adapters/whatsapp/node/.status.json` again — both should reflect a
recent, real run driven by the service, not the manual runs from Steps
4-5.

## Step 8: Access the dashboard — SSH tunnel, not a public port

The ops dashboard (`/status`, `/outlook`, `/whatsapp`, `/linkedin`,
`/resolution`) and the **`/inbox` triage frontend** (the actual client-
facing UI — contact list, per-contact detail/context panel, merge/hide
tools) are the same Flask app on the same port (`scripts/onboarding/app.py`)
— there is no separate frontend service or build step to deploy.
`comms-dashboard.service` from Step 7 already serves both. `/inbox`
pushes new messages to an open browser tab live (Server-Sent Events on
`/inbox/events`, triggered by a Postgres `NOTIFY` any adapter fires on a
new message) — no polling, no manual refresh needed once a tab is open.
It has **no login of its own**, so it's meant to be reached via an SSH
tunnel, never exposed publicly:
```bash
ssh -L 5000:localhost:5000 <user>@<aws-ip>
```
then browse `http://localhost:5000` locally. **Confirm the AWS security
group has no public inbound rule for port 5000** before calling this
step done — the tunnel only helps if there's no other way in.

## Step 9: Full verification pass

```bash
python scripts/pipe_health.py
python scripts/monitor.py
```
`monitor.py` should report all three channels healthy (exit code 0). If
Supabase MCP is available, run `get_advisors` once here too — free
signal on anything security/performance related worth knowing about
before calling this deploy done.

**Also open `/inbox` itself through the SSH tunnel from Step 8** and
confirm real contacts and their AI-generated context/summary render (not
just that the page loads empty) — this is the actual client-facing
surface, not just plumbing, and an empty-looking page with no console
errors is exactly what a blank `ANTHROPIC_API_KEY` (Step 1) looks like,
since `ai_brief` failures are silent by design. Leave the tab open,
trigger a sync manually (`python -m adapters.whatsapp.sync` or wait for
the next scheduled run), and confirm the list updates on its own —
that's the SSE push from Step 8 working end to end, not just registered.

**This deploy isn't "done" until all of the above pass for real** — not
"the commands didn't error," but the verification command in each step
actually returned what it should. If something's still red, stop and
fix that step rather than moving on and hoping it resolves itself.
