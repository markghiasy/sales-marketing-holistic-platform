# Reply-Quote Bubble (Outlook) — Design

## Goal

In the triage inbox's message detail panel, when an Outlook email is a
reply to another message that's already in this same contact's
conversation, show a WhatsApp-style quote preview inside the reply's
bubble: a collapsed one-line excerpt of the original message, expandable
to the full text, with a jump-to-original affordance when the original is
part of the currently-rendered thread.

## Scope

- **Outlook only.** In-Reply-To is an email/RFC-5322 concept; WhatsApp and
  LinkedIn have no equivalent header in what we ingest.
- **Only shown when the quoted original is a message already in this
  conversation's own displayed set** (i.e. a message `get_detail()`
  already returns for this `person_key`). If the reply references a
  message we don't have, or that's currently hidden by the inbox's own
  filters (automated-sender / stale-unknown hiding), no quote bubble is
  shown at all — same as today's behavior. There is no fallback path that
  extracts a quoted excerpt from the replying email's own raw HTML; that
  content is discarded today by `_strip_html`'s quote-cut logic and stays
  discarded.
- Matching is exact (`In-Reply-To` header value == another message's
  `internetMessageId`), not text-similarity based.

## Data model

`message` gains a nullable column:

```sql
in_reply_to_external_id text null
```

Stores the raw `In-Reply-To` header value (already angle-bracket-wrapped,
e.g. `<abc@example.com>`) verbatim — the same string shape as
`message.external_id`, which is already keyed on `internetMessageId`, so
a straight string-equality join works with no normalization.

Real data check (2026-09-17): `internetMessageHeaders` is already part of
Outlook's `$select` fetch and already stored in full in `message.raw` —
471 of 7,035 currently-stored messages already carry this header, so no
new Graph API scope or select change is needed, and existing messages
backfill the same way `is_automated`/the HTML cleanup fixes did (re-derive
from stored `raw`, no re-sync required).

## Envelope / adapter

- `Envelope` gains `in_reply_to_external_id: str | None = None`.
- `adapters/outlook/sync.py`'s `_to_envelope` parses it from
  `raw["internetMessageHeaders"]` (case-insensitive header name match,
  same pattern as the existing List-Unsubscribe tier-1 check) — the value
  is stored as-is, no cleanup.
- `store_writer.upsert()`'s message INSERT gains this column, written
  straight from `env.in_reply_to_external_id`.

## Query layer (`adapters/inbox_query.py`)

`get_detail()` already fetches every message for a `person_key` into
`rows` (one row per message) before grouping into threads. After that
fetch:

1. Build `external_id_to_message_id: dict[str, str]` from the same row
   set (needs `m.external_id` added to the main SELECT — not currently
   selected).
2. For each row, if its `in_reply_to_external_id` is non-null and present
   as a key in that map, resolve `quoted_message_id` (the matched
   message's own id) and `quoted_preview` (that matched message's own
   `body_text`, already clean).
3. `ThreadMessage` gains two fields:
   - `quoted_message_id: str | None`
   - `quoted_preview: str | None`

No new query round-trip — this is a dict lookup against data already in
hand.

## Frontend

- Every rendered message bubble gets `data-message-id="${m.id}"` (the
  `ThreadMessage`/JSON payload need to carry `id` through — currently
  `ThreadMessage` has no `id` field at all; add one, plain message id,
  Outlook-only concept elsewhere too so no channel-conditional logic
  needed).
- When `m.quoted_preview` is present, render a collapsed quote block
  above the message text: one line of `quoted_preview` (CSS
  `text-overflow: ellipsis`, single line), click to toggle an expanded
  state showing the full `quoted_preview` text.
- A small jump control (e.g. an arrow icon) next to the quote block,
  visible only when `m.quoted_message_id` is set, scrolls
  `[data-message-id="${m.quoted_message_id}"]` into view (`scrollIntoView`)
  and briefly highlights it (a CSS class removed after a short timeout).

## Testing

- `_to_envelope`: parses `In-Reply-To` header (present / absent / header
  name case variation).
- `store_writer.upsert()`: persists `in_reply_to_external_id`.
- `inbox_query.get_detail()`: matches within the same conversation's
  fetched set; leaves `quoted_message_id`/`quoted_preview` both `None`
  when no match (header absent, or references a message outside this
  conversation's own set).
- Backfill script (same pattern as the `is_automated`/HTML-cleanup
  backfills): re-derive `in_reply_to_external_id` from stored `raw` for
  all existing Outlook messages.

## Out of scope (explicitly deferred)

- Showing a quote preview when the original isn't in this conversation's
  own displayed set (would require extracting/cleaning the quoted excerpt
  from the replying email's own raw HTML — separate, larger effort).
- WhatsApp/LinkedIn reply-quoting (no In-Reply-To equivalent ingested
  today).
