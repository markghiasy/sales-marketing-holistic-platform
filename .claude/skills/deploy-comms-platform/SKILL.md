---
name: deploy-comms-platform
description: Deploy this repo to a new instance (Mark's AWS box, or any fresh checkout) — walks through env setup, Supabase, the three channel auths, and long-running services, with a verification command after every step so a failure surfaces immediately instead of silently moving on. Use when the user wants to deploy, set up, or connect this platform on a machine that isn't already running it.
---

# Deploy: Comms & Outreach Platform

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

## Step 0: Confirm the target environment

Ask the operator (don't guess): what OS is this machine running, and is
this a fresh checkout or an existing one being updated?

```bash
uname -a          # Linux/macOS — shows the kernel + distro hints
cat /etc/os-release 2>/dev/null  # Linux — exact distro + version
```
On Windows, `runbook.md`'s existing "Deploying a clean instance" /
scheduling sections apply as written (they were built and verified
there). Everything below assumes Linux — adjust or stop and ask if the
target turns out to be something else (macOS, a different init system
than systemd).

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

**Verify:** `.env` has no blank `=` lines left for the fields above
(`MONITOR_ALERT_WEBHOOK_URL` and the `LINKEDIN_*` rate-limit vars are
fine to leave at their defaults):
```bash
grep -E '^(AZURE_TENANT_ID|AZURE_CLIENT_ID|OUTLOOK_MAILBOX|LINKEDIN_SELF_PROFILE_URL|DATABASE_URL|WHATSAPP_AUTH_ENCRYPTION_KEY|MONITOR_NTFY_TOPIC)=$' .env
```
This should print nothing. If it prints a line, that field is still
blank — go back and fill it before continuing.

## Step 2: Supabase — apply all 6 migrations, in order

**Confirm with the operator first**: this writes schema to their real
Supabase project. Not reversible by this skill (some migrations create
tables; none currently drop anything, but treat it as a one-way door).

Migrations are NOT applied automatically the way they are for a local
Docker Postgres (that only happens via
`docker-entrypoint-initdb.d` on an empty volume, which doesn't apply
here) — apply each file by hand, in order:

```bash
for f in db/migrations/*.sql; do
  echo "applying $f"
  psql "$DATABASE_URL" -f "$f" || { echo "FAILED at $f — stop here"; break; }
done
```
(No `psql` installed? Same effect via Python:
```bash
python3 -c "
import psycopg, glob, os
dsn = os.environ.get('DATABASE_URL') or open('.env').read()  # prefer an exported env var
for f in sorted(glob.glob('db/migrations/*.sql')):
    print('applying', f)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(open(f).read())
        conn.commit()
"
```
— but load `DATABASE_URL` from `.env` properly first, e.g. `export
$(grep DATABASE_URL .env)` before running this.)

**Verify — all 9 tables + 4 views + the tables added since exist:**
```sql
select table_name from information_schema.tables where table_schema = 'public' order by 1;
```
Expect: `action, contact_graph_strength, contact_last_message,
contact_reciprocity, contact_stats, event, fact, graph_contact,
identity, link_candidate, linkedin_connection, merge_log, message,
message_participant, organization, outreach, person, thread` (18 names
— re-run `ls db/migrations/` and re-check this list if migrations have
been added since this skill was written; the count should track
1:1-ish with what the migrations create).

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
`/resolution`) is one Flask app on one port with **no login of its
own**. It's meant to be reached via an SSH tunnel, never exposed
publicly:
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

**This deploy isn't "done" until all of the above pass for real** — not
"the commands didn't error," but the verification command in each step
actually returned what it should. If something's still red, stop and
fix that step rather than moving on and hoping it resolves itself.
