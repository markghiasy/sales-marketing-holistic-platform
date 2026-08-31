# Onboarding Dashboard — Design

**Date:** 2026-08-31
**Status:** Approved by Eva, pending implementation plan

## Problem

Connecting Outlook, LinkedIn, and WhatsApp today means running three
separate CLI commands, each with a different interaction model (device
code, an interactive browser login, a QR scan). This is fine for Eva,
who built it, but not for Mark's team, who need to be able to connect
their own accounts without going through her — every manual step is a
future support request landing back on her.

## Scope

- **In scope:** a single web dashboard that walks a non-technical person
  through connecting all three channels, reusing the existing adapter
  auth mechanisms as-is (no changes to how Outlook/LinkedIn/WhatsApp
  actually authenticate).
- **Out of scope:** multi-tenant account isolation (this only serves
  Mark's own internal accounts, confirmed with Eva — not a product other
  customers self-serve into). Packaging LinkedIn's helper as a
  zero-dependency single executable (ruled out — the dashboard will
  instead tell the user to have Python and Node installed first).
  Deploying this to real hosting — it runs locally for now, the same as
  every other script in this repo, and moves wherever the backend ends
  up once the Supabase/cloud migration happens, without needing a
  redesign.

## Architecture

A small Flask app, one process, no new database schema — it only needs
to get credentials into the same local files the existing sync scripts
already read (`adapters/outlook/.token_cache.bin`,
`adapters/linkedin/.storage_state.json`,
`adapters/whatsapp/node/.auth_state/`). The dashboard is a single page
with three panels, each polling its own JSON status endpoint every
1.5s (same auto-refresh trick already proven in `qr_viewer.html`) so
the page updates itself without the user doing anything.

```
Browser (dashboard)
  │  poll every 1.5s
  ▼
Flask app (scripts/onboarding/app.py)
  ├── /outlook/*   → wraps adapters/outlook/client.py's device-code flow
  ├── /whatsapp/*  → ensures ingest.js is running, reads .status.json / serves qr.png
  └── /linkedin/*  → serves a downloadable helper script + accepts its upload
```

## Components

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
Eva clicking through it herself.
