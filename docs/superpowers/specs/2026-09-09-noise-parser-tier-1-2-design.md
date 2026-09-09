# Noise Parser Tier 1 + Tier 2 — Design

**Date:** 2026-09-09
**Status:** Approved by Eva, pending implementation plan

## Problem

Build plan §9's noise parser has three tiers, cheapest first: tier 1
(deterministic, free), tier 2 (relational, effectively free), tier 3
(semantic, real money — blocked on Mark providing a commercial model API
account and budget, still pending despite Eva already following up).

Tiers 1 and 2 need no model call and are genuinely unblocked, but neither
is fully built. Only one of tier 1's four signals exists today — Graph's
own Focused/Other classification, already wired into
`adapters/outlook/sync.py`'s `_to_envelope`. The remaining three (List-
Unsubscribe header, no-reply/bulk sender pattern, known automated domain)
are unbuilt. Tier 2 has no query surface at all, even though the
underlying data — reply counts, reciprocity — already exists from earlier
§10/§12 work.

**A real, independent bug surfaced while exploring this:**
`adapters/store_writer.py`'s `upsert()` never includes `is_automated` in
its `insert into message` column list. The column exists (schema default
`false`), `Envelope.is_automated` exists and is correctly computed at the
adapter level for the one signal that's built — but none of it reaches the
database. Every message ingested to date has `is_automated = false`
regardless of reality.

## Scope

**In scope:**
1. Fix `store_writer.upsert()` to persist `is_automated`.
2. Complete Outlook tier 1: List-Unsubscribe header, sender pattern,
   sender domain — combined with the existing classification signal via
   OR.
3. Tier 2: one query function, `adapters/reply_signal.py`, built on the
   existing `contact_stats`/`contact_reciprocity` views
   (`db/migrations/0002_graph_views.sql`).

**Not in scope:**
- No triage inbox or any UI (Block C, not built yet — tier 2 has no
  caller until it exists).
- No WhatsApp/LinkedIn changes — tier 1's remaining signals need email
  headers/domains, which neither channel has (phone numbers and member
  ids respectively).
- No tier 3 / model calls — still blocked on Mark's decision.

## Tier 1 — where the logic lives, and why

**Directly in `_to_envelope`, not a shared module.** An earlier framing
considered a generic `adapters/noise_parser.py` tier-1 function taking
headers/from_handle as parameters, callable by any adapter. Decided
against — List-Unsubscribe headers and email domains only exist for
Outlook; §3 fixes the channel count at three, with no fourth ever, and
WhatsApp/LinkedIn handles have no header/domain concept at all. There is
no second caller today, so the abstraction has nothing to generalize
over. If a future channel genuinely needs equivalent logic, extract then
— not preemptively.

**Signals combine with OR**, matching §9's framing of tier 1 as a binary,
high-confidence filter ("catches most of the volume... free"), not a
graded score like tier 2/3: `is_automated = True` if Graph classification
== `"other"`, OR a `List-Unsubscribe` header is present, OR the sender's
local-part matches a known automated pattern, OR the sender's domain is a
known automated domain.

**List-Unsubscribe detection reuses data already being fetched.**
`_resolve_sent_at` already reads `raw["internetMessageHeaders"]` (for the
`Date` header) — the same list gets scanned for a header named
`list-unsubscribe` (case-insensitive, presence-only check). No new Graph
`$select` fields or scopes required.

**Sender pattern list** (case-insensitive match against the local-part,
the substring before `@`): `noreply`, `no-reply`, `donotreply`,
`do-not-reply`, `notifications`, `notification`, `alerts`, `alert`,
`mailer-daemon`, `postmaster`. Deliberately a separate list from the
identity-resolution design's generic-role-address list (`support@`,
`info@`, `admin@`, etc.) — these mean different things (automated-sender
signal vs. shared-mailbox signal) and should evolve independently, even
though the two lists could theoretically overlap on some strings.

**Domain list**: a small seed set of common transactional/ESP domains
(e.g. `sendgrid.net`, `mailgun.org`, `amazonses.com`, `mailchimp.com`,
`notifications.google.com`), kept as a plain Python list next to the
tier-1 code — not a config file or DB table. A handful of entries,
versioned in git, extended with a one-line diff as real data suggests
additions.

**Known real-data limitation, stated plainly rather than discovered
later:** the seed lists above are reasonable guesses, not verified
against this mailbox's actual automated senders — the local Postgres
instance was down while designing this, so there was no real data to
check against. Same treatment as Rule 1/4 in the identity-resolution
work: run tier 1 against real ingested mail once implemented, inspect
what it catches/misses by hand, and extend the lists as a one-line
change, not a design change.

## Tier 2 — reply signal lookup

**Its own module, `adapters/reply_signal.py`** — unlike tier 1, this is
genuinely channel-agnostic: it operates on `contact_key`
(`coalesce(identity.person_id, identity.id)`, the same grouping the §10
views already use), post-ingest, not embedded in any one adapter's
parsing code.

```
reply_signal(cur, contact_key: str) -> ReplySignal
  sent_count, received_count, reciprocity_ratio, last_contact_at
  — all None when the contact has no message history at all
```

No new SQL beyond a join/select against the existing
`contact_stats`/`contact_reciprocity` views — no new schema. Not called
from anywhere yet; Block C's triage inbox is the eventual consumer, and
it doesn't exist yet. This is infrastructure, verified only at the unit
level until that caller exists.

## The is_automated fix

One-line addition to `store_writer.upsert()`'s existing column list and
value tuple — no schema change, no migration (the column and its default
already exist). Worth stating plainly: this changes real behavior, not
just fixes an isolated bug — every message ingested from this point
forward gets a real `is_automated` value instead of always-false. Nothing
downstream reads the field yet, so there's no existing consumer to break,
but future Block C code will read real values instead of the silent
always-false that existed before.

## Testing

TDD throughout, following this project's existing test conventions
(`tests/test_store_writer.py`'s `db_conn` fixture pattern,
`tests/test_outlook_sync.py`'s `TestToEnvelope._BASE_RAW` fixture
pattern):
- `store_writer`: an envelope with `is_automated=True`/`False` produces a
  matching `message.is_automated` value.
- Outlook tier 1: List-Unsubscribe header present → `True`; known sender
  pattern → `True`; known domain → `True`; none of the above and a
  `"focused"` classification → `False`; any single signal alone is
  sufficient (OR, not AND).
- `reply_signal`: a contact with real message history returns real
  values; a contact with none returns an all-`None` object, not an
  error.

After implementation, if Docker/local Postgres is available, run tier 1
against real ingested mail and inspect the hit rate by hand — same
verification step already used for Rule 1/4.
