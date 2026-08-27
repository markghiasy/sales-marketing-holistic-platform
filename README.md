# Comms & Outreach Platform — MVP 1.0

Block A skeleton. See the full build plan (§ references throughout this repo
point back to it) for the complete design — this README only covers what's
here and how to run it.

## What's in Block A

- `db/migrations/0001_init.sql` — the store schema (§7): one Postgres
  database, everything downstream reads or writes these tables.
- `adapters/envelope.py` — the shared vendor-payload boundary every
  channel normalises to (§6). `adapters/store_writer.py` is the one place
  that writes an envelope into the store — every adapter calls this
  instead of reimplementing the upsert.
- `adapters/outlook/` — Graph auth (`client.py`) + the sync entrypoint
  (`sync.py`), idempotent on `internetMessageId`. `contacts_sync.py` pulls
  `/me/contacts` into `graph_contact` (§8's bridge source) — no matching
  logic, that's Block B. Empty on this mailbox; wired up regardless.
- `adapters/whatsapp/` — split across two languages on purpose: no mature
  Python multi-device WhatsApp library exists, so `node/ingest.js`
  (Baileys) is the connection layer and does nothing but write raw
  messages to a JSON-lines queue; `sync.py` reads that queue, maps to the
  shared envelope, and upserts — same store-writing code path as every
  other channel. Idempotent on WhatsApp's own message id (`key.id`),
  which — unlike LinkedIn — the protocol gives us natively, no guessing.
- `adapters/linkedin/` — three paths, each doing a different job:
  - **Initial backfill: LinkedIn's own data export.** `request_export.py`
    triggers the official "download my data" archive (Settings > Data
    Privacy); `export_sync.py` checks for a finished one, downloads it,
    and parses `messages.csv`. Not real-time (~24h turnaround per
    request), and not ToS-grey either — it's a self-service export, not
    scraping. Good for the one-time historical fill; too slow to be the
    ongoing sync.
  - **Ongoing real-time (planned, not built): SSE push.** LinkedIn's own
    messaging UI holds open a Server-Sent-Events connection rather than
    polling — same shape as WhatsApp's persistent socket. See runbook for
    why this isn't implemented yet (needs a real message captured first to
    know the topic format) and the plan for building it.
  - **Backup: live session scraping.** `login.py` (one-time interactive
    login) + `client.py`/`sync.py` read the messaging page via network
    interception, human-paced per §13 rule 2. Fallback if the export path
    or the SSE approach turn out unworkable. Rate limits in `config.py`
    are placeholders — not yet signed off by Mark.
- `scripts/pipe_health.py` — heartbeat: is the store reachable, did
  ingestion run recently.
- `scripts/export.py` — full re-importable dump of the store.

Not in Block A: triage inbox, noise parser, network graph, task layer,
outreach engine. Those are Blocks B–E — see `runbook.md` for the checkpoint
this block needs to pass before B starts.

## Running it

```bash
cp .env.example .env   # fill in AZURE_TENANT_ID, AZURE_CLIENT_ID, OUTLOOK_MAILBOX
docker compose up -d   # Postgres, schema applied on first boot
pip install -e .
python -m adapters.outlook.sync
```

First run opens a device-code auth prompt — sign in as the mailbox owner.
Subsequent runs reuse the cached token silently.
