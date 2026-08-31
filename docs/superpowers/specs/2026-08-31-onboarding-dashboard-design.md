# Ops Dashboard (Onboarding + Live Status) — Design

**Date:** 2026-08-31
**Status:** Approved by Eva, pending implementation plan

## Problem

Connecting Outlook, LinkedIn, and WhatsApp today means running three
separate CLI commands, each with a different interaction model (device
code, an interactive browser login, a QR scan). This is fine for Eva,
who built it, but not for Mark's team, who need to be able to connect
their own accounts without going through her — every manual step is a
future support request landing back on her.

Separately, `scripts/monitor.py` already checks channel health and
alerts via ntfy, but only when Windows Task Scheduler fires it every 15
minutes — there's no live view, just a periodic check-and-exit.
Revised 2026-08-31 (Eva's idea): fold both into one always-running
service instead of two separate things. The connect flow and the
ongoing health view are the same underlying question — "what's the
state of each channel right now" — so they belong in one page, not a
dashboard for setup and a separate cron job for health.

## Scope

- **In scope:** a single, continuously-running web app with three
  panels (Outlook/LinkedIn/WhatsApp) that both (a) walks a
  non-technical person through connecting an account, reusing the
  existing adapter auth mechanisms as-is, and (b) shows each channel's
  live health once connected, running the same background checks
  `scripts/monitor.py` already does (imported, not reimplemented) and
  firing the same ntfy alerts — regardless of whether anyone has the
  page open.
- **Out of scope:** multi-tenant account isolation (this only serves
  Mark's own internal accounts, confirmed with Eva — not a product other
  customers self-serve into). Packaging LinkedIn's helper as a
  zero-dependency single executable (ruled out — the dashboard will
  instead tell the user to have Python and Node installed first).
  **Where this runs, long-term.** This service needs to run
  continuously to do its job (the health-checking half doesn't work if
  the process isn't alive) — the same requirement WhatsApp's `ingest.js`
  connector already has, and the same open question: a laptop that gets
  closed takes the whole thing down with it. That's an infrastructure
  decision for Eva and Mark to make together (tied to the pending
  Supabase/cloud migration), not something this design resolves. It
  runs locally for development the same as everything else in this repo
  today; nothing about the design below assumes a particular host, so
  it moves without a rewrite once that decision is made.

## Architecture

A small Flask app, one process, no new database schema — it only needs
to get credentials into the same local files the existing sync scripts
already read (`adapters/outlook/.token_cache.bin`,
`adapters/linkedin/.storage_state.json`,
`adapters/whatsapp/node/.auth_state/`). The dashboard is a single page
with three panels, each polling its own JSON status endpoint every
1.5s (same auto-refresh trick already proven in `qr_viewer.html`) so
the page updates itself without the user doing anything.

The process also runs a background thread that does exactly what
`scripts/monitor.py` does today, on the same interval (15 min,
unchanged), by importing and calling its existing check functions
rather than duplicating the logic — same ntfy alerts, same cooldown
state file. This thread runs independent of any browser being open;
the page's live view and the background alert are two ways of surfacing
the same underlying check, not two separate mechanisms. Once this
ships, the standalone `CommsPlatformMonitor` Task Scheduler entry
becomes redundant and should be retired — one persistent process doing
the job instead of a page plus a separate scheduled task.

```
Browser (dashboard)                    ntfy.sh
  │  poll every 1.5s                      ▲
  ▼                                        │ every 15 min, regardless of
Flask app (scripts/onboarding/app.py)      │ whether the browser is open
  ├── /outlook/*   → wraps adapters/outlook/client.py's device-code flow
  ├── /whatsapp/*  → ensures ingest.js is running, reads .status.json / serves qr.png
  ├── /linkedin/*  → serves a downloadable helper script + accepts its upload
  ├── /status      → live JSON for all three panels' ongoing health
  └── background thread ─────────────────┘ (imports scripts/monitor.py's checks)
```

## Components

**UI copy tone.** The end users of this page are Mark's own team, up to
and including people above him — this reads as an internal ops tool to
Eva, but to them it's a product interface. Wording throughout should be
written from their side of the screen ("for your convenience, connect
each account below") rather than leaking the internal reason it exists
("so you don't need to ask Eva every time") — same principle as any
other user-facing product copy, not an ops-tool afterthought.

**Outlook panel.** "Connect" triggers the existing device-code flow
server-side; the code and verification URL are returned to the page
immediately and shown as plain text (the user reads it, opens
microsoft.com/devicelogin on any device, enters it). The page polls
`/outlook/status`, which just checks whether `.token_cache.bin` now
holds a valid token, and flips to "Connected as `<mailbox>`" once it
does. Nothing here needs a local browser — it's the same flow already
used, just surfaced in a page instead of a terminal.

**WhatsApp panel.** "Connect" starts `ingest.js` as a subprocess if it
isn't already running. The panel embeds the QR image with the same
1.5s cache-busting refresh as `qr_viewer.html`, and separately polls
`/whatsapp/status`, which reads `.status.json` (built this week) and
shows its state directly: `qr_pending` → "scan with your phone",
`connected` → "Connected as `<number>`", `logged_out` → "session
expired, scan the new code below", `crashed` → an error with a retry
button. This reuses the diagnostic work already done rather than
building new state logic.

**LinkedIn panel.** This is the one channel that genuinely needs an
interactive browser login somewhere, and it should happen on the
account owner's own machine — both because that's the only way to
actually complete a login with 2FA, and because logging in from the
person's normal device is more consistent with the conservative,
human-paced posture Mark ratified than anything server-side would be.
The panel has a "Download connection tool" button that serves a small
script (a `.bat` wrapper on Windows, equivalent on Mac) which runs
`python -m adapters.linkedin.login` — the existing flow, unchanged. The
dashboard page states plainly, before the button: "Requires Python and
Node installed on your computer first" with links to the installers.
Once `login.py` finishes and writes `.storage_state.json` locally, the
script POSTs that file to `/linkedin/upload-session` on the dashboard.
"Authenticated" here means a one-time token embedded in the downloaded
script itself (generated fresh per download, single-use) — enough to
stop a random upload from overwriting someone's session, not a full
account system, since this only ever runs on Mark's own internal
network for Mark's own accounts. The panel's next poll of
`/linkedin/status` shows "Connected" once the upload lands.

## Data flow

No new persistent store. Every panel's "connected" state is derived by
reading the exact same local file the corresponding sync script already
checks for (`.token_cache.bin` existing and valid, `.status.json`'s
`state` field, `.storage_state.json` existing). The dashboard is a view
over state that already exists — it doesn't introduce a second source
of truth.

## Error handling

- Outlook device code expiring before the user finishes: `/outlook/status`
  reports `expired`, the panel shows a "get a new code" button rather
  than hanging on a dead code.
- WhatsApp: already covered by the `.status.json` states above —
  `crashed`/`logged_out` are surfaced with plain-language next steps
  instead of a generic failure.
- LinkedIn helper failing to run (Python/Node missing, blocked by
  antivirus, etc.): the download page includes a short troubleshooting
  list; if someone gets stuck, the existing manual path
  (`python -m adapters.linkedin.login` run by Eva) still works
  unchanged as a fallback — this dashboard doesn't replace that, it
  removes the need for it in the common case.

## Testing

Flask routes get unit tests the same way the rest of this repo does —
mocked/stubbed I/O (fake token cache states, fake `.status.json`
contents), not real live sessions, matching the existing test suite's
pattern. The real validation, consistent with how every other piece of
this project has been checked, is a live walkthrough by someone who
didn't build it — ideally a non-technical person on Mark's side
actually connecting a real account through the dashboard, not just
Eva clicking through it herself. Separately, the background-alerting
half needs its own real check: close the browser tab entirely, force a
channel unhealthy, and confirm the ntfy alert still arrives — the exact
behavior the merge was for, not something to assume works because the
code looks right.
