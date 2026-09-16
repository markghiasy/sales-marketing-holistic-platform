# Triage Inbox — Real Data + LLM Brief — Design

**Date:** 2026-09-16
**Status:** Approved by Eva, pending implementation plan

## Problem

`/inbox` (`scripts/onboarding/templates/inbox.html`, Linear `STU-197`) is a
2026-09-14 demo prototype for Mark — every conversation, topic tag,
`context` bullet, network-graph relationship, and preview summary is a
hand-written entry in a `MOCK_CONVERSATIONS` JS array. Nothing reads the
real `message`/`identity`/`person`/`fact` tables, and no LLM call exists
anywhere in this codebase yet (`ANTHROPIC_API_KEY` landed in `.env` on
demo day but has never been used).

This is Linear `STU-131` ("[Block C] Triage inbox", Backlog, not started)
— building it for real, not extending the demo file. `/inbox` gets
replaced in place; the mock array is deleted (git history keeps it).

## Scope

**In scope:**
1. Real message/identity data backing the inbox list and detail panel
   (rows, channel filter, thread grouping, unread/unanswered filters).
2. `thread.last_read_at` — a real (if app-local) read/unread signal, since
   the schema has no mailbox-sourced read state at all.
3. An LLM precompute pipeline (`adapters/ai_brief.py`) that runs after
   each channel's sync + resolution, producing per-person `summary`,
   `context` bullets, `urgency`, and `graph` (org + LLM-inferred
   relationships) — cached in a new `ai_brief` table, never called live
   from a page request.
4. Network graph rendering wired to `ai_brief.graph` instead of a
   hand-written per-contact object.

**Not in scope (explicitly deferred):**
- **Draft replies.** No real draft generation this pass — that's the next
  phase (the project-management/action layer). The "Draft ready" badge
  and "Has draft ready" filter stay in the UI (removing them would be
  premature — the next phase adds the field they key off), but nothing
  will ever set `has_draft = true` yet, so they're inert, not broken. The
  detail panel's "AI draft reply" section also stays, its body replaced
  with a static "Draft replies — under development" placeholder instead
  of being deleted.
- Actually sending anything ("Use this draft" stays a dead button).
- The top search bar's real semantic search (still visual-only).
- Any UI for reviewing/correcting an LLM-generated brief before it's
  shown — if quality turns out bad, that's a follow-up decision, not
  scoped here.

## Data model changes

### `thread.last_read_at`

No mailbox-sourced read state exists anywhere in this schema (Graph's
`isRead` is only ever quarantined in `message.raw`, which nothing reads —
by design, per `db/migrations/0001_init.sql`'s own comment). Eva's call:
build our own app-local read tracking rather than plumb the real mailbox
state through, and backfill today's data as already-read.

```sql
alter table thread add column last_read_at timestamptz;
update thread set last_read_at = now();
```

- **Unread** = `thread.last_message_at > thread.last_read_at` (or
  `last_read_at is null`). New threads default `null` → unread by
  construction, no extra write needed at ingest time.
- Opening a person's detail panel sets `last_read_at = now()` for every
  thread belonging to that person (all channels).
- A new inbound message landing in an already-read thread naturally flips
  it back to unread — `last_message_at` moves past `last_read_at` with no
  extra bookkeeping.
- A person-level "unread" (what the list row shows) is `any` of that
  person's threads being unread.
- For testing: no seed script is in scope here — Eva will hand-flip a
  few real threads' `last_read_at` back to `null` per channel once this
  ships, to check the UI live against real rows in each state.

### `ai_brief` table

```sql
create table ai_brief (
    person_key         text primary key,  -- coalesce(identity.person_id, identity.id),
                                           -- same grouping as contact_stats/contact_reciprocity
    summary            text not null,     -- short third-person action-summary, list row preview
    context            jsonb not null,    -- array of first-person-voice full sentences
    graph              jsonb not null,    -- {org: {name, blurb}|null, people: [{name, relation}]}
    urgency            smallint not null, -- 1-3, same rough meaning as the old mock "priority"
    model              text not null,
    prompt_version     text not null,
    generated_at       timestamptz not null default now()
);
```

One row per resolved contact (`person_key`), not per message or per
sync — a new sync that touches a person already in `ai_brief` overwrites
their row rather than appending, since a brief only makes sense as "the
latest picture of this person."

## Precompute pipeline

Hooks onto the same place `STU-166`'s auto-resolution already runs: each
adapter's `run()` calls `resolution.run_best_effort()` on its success
path (`adapters/outlook/sync.py`, `adapters/whatsapp/sync.py`,
`adapters/linkedin/sync.py`). Add one more step after that call:
`ai_brief.refresh_touched(cur, touched_person_keys)`, where
`touched_person_keys` is the set of `person_key`s with a message ingested
in *this* sync run — not a full-table recompute every time. Each adapter
already knows which envelopes it just wrote; threading that set through
to the new call is an implementation-plan-level detail, not a design
question.

For each touched `person_key`, `generate_brief(cur, person_key)`:
1. Pulls every real message across **all** of that person's identities
   (all channels, all threads) via
   `message join message_participant join identity where
   coalesce(identity.person_id, identity.id) = person_key` — this is
   already the same join `contact_stats` uses, just selecting messages
   instead of aggregates.
2. Pulls `fact` rows (`works_at`/`has_title`) for those identities, and
   `reply_signal(cur, person_key)` for the relational numbers.
3. Sends all of it to the LLM in one call — this single call is where all
   three of Eva's context dimensions come from at once: graph
   nodes/relationships, narrative context bullets, and the
   cross-channel/cross-thread synthesis (because the input to the call
   already spans every channel and thread for this person, not one at a
   time).
4. Parses the model's structured JSON response into `summary`, `context`,
   `graph`, `urgency`, and upserts the `ai_brief` row.

A failed or malformed LLM response for one person must not fail the
whole sync (same isolation philosophy as `resolution.run_best_effort()`)
— log and skip that person's brief for this run; their old `ai_brief` row
(if any) stays as-is until the next sync retries them.

## LLM call

**Model: Haiku 4.5** (`ANTHROPIC_MODEL`, configurable, not hardcoded —
switching to Sonnet 5 for quality is a one-line env change, not a design
change). This is structured extraction + summarization from a modest
amount of real text per call, run in bulk across many contacts on every
sync — not a task that needs Sonnet-level reasoning, and the recurring,
multi-contact-per-sync call pattern makes Haiku's lower cost/latency the
right default. Revisit only if real output quality (especially inferring
implicit relationships like "X said they'd introduce Y") turns out
unreliable in practice.

**Output schema** (JSON, validated before writing to `ai_brief`):
```json
{
  "summary": "short third-person action-summary, one sentence",
  "context": ["full first-person-voice sentence", "..."],
  "graph": {
    "org": {"name": "...", "blurb": "..."} ,
    "people": [{"name": "...", "relation": "short phrase"}]
  },
  "urgency": 1
}
```
`graph.org` may be `null` (no `works_at` fact and nothing in message text
implies one). `graph.people` may be empty. The prompt instructs the model
to only include a person/relation it can point to real message text or a
`fact` row for — no inventing relationships the way the mock data did.

## Network graph rendering

`renderGraph()` (already built for the mock data, including the
clickable-node/relationship-label work from the 2026-09-14 demo
follow-up) needs no rewrite — it already takes a `{org, people}` shape.
Only its data source changes: `c.graph` becomes `ai_brief.graph` fetched
per person, instead of a hand-written literal.

## Route / UI changes

- `/inbox` stays the same route; `MOCK_CONVERSATIONS` and the mock-only
  parts of the file's own header comment are deleted.
- List query: one row per `person_key` with at least one message,
  `summary` from `ai_brief` (fall back to the literal latest
  `message.body_text`, truncated, if no `ai_brief` row exists yet for a
  brand-new contact ahead of that sync's precompute step), `urgency` for
  Priority sort, per-person unread via `thread.last_read_at` as above.
- Detail panel: threads grouped by real `thread` rows (channel +
  `thread.title`, which is already nullable — WhatsApp/LinkedIn threads
  render with no subject header, exactly like the non-Outlook contacts
  already do in the current mock version), messages ordered by
  `sent_at`. Context section reads `ai_brief.context`. Draft section
  becomes the static "under development" placeholder described above.

## Testing

TDD, following this project's existing conventions:
- `thread.last_read_at` migration + the read/unread query logic: a thread
  with `last_message_at > last_read_at` (or `last_read_at is null`) is
  unread; opening a person's detail marks all their threads read; a new
  inbound message on a read thread flips it back to unread.
- `ai_brief.generate_brief`: mock the Anthropic client, assert the
  DB-read inputs (messages across channels, facts, reply_signal) are
  assembled correctly and the parsed response upserts the right
  `person_key` row; a malformed/failed response is caught and skipped,
  not raised.
- `ai_brief.refresh_touched`: only the given `person_key`s get
  regenerated, not the whole table.
- Flask route: list/detail rendering against a `db_conn` fixture seeded
  with real-shaped rows (reusing `tests/test_store_writer.py`'s pattern),
  no live Anthropic call in tests.
