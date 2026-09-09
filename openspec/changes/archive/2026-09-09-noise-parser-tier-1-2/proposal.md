## Why

Build plan §9's noise parser has three tiers. Tier 3 (semantic, model-assisted)
is blocked on Mark providing a commercial model API account and budget — still
pending despite Eva already following up. Tiers 1 (deterministic) and 2
(relational) need no model call and are genuinely unblocked, but neither is
fully built: Outlook's `_to_envelope` only implements one of tier 1's four
signals (Graph's Focused/Other classification), and tier 2 has no query
surface at all yet, even though the underlying data (`contact_stats`,
`contact_reciprocity` views) already exists from earlier §10/§12 work.

Separately, exploring this surfaced a real, independent bug worth fixing in
the same change: `adapters/store_writer.py`'s `upsert()` never includes
`is_automated` in its `insert into message` column list, so every message
ingested today is silently `is_automated = false` in the store regardless of
what any tier computes — including the one signal (`inferenceClassification`)
that already works correctly at the adapter level.

## What Changes

- Fix `store_writer.upsert()` to actually persist `is_automated` — currently
  omitted from the INSERT entirely.
- Complete tier 1 in `adapters/outlook/sync.py`'s `_to_envelope`: add
  List-Unsubscribe header detection (header data already fetched, no new
  Graph scope needed), no-reply/bulk sender local-part pattern matching, and
  a documented seed list of known automated domains. Combined with the
  existing Graph-classification signal via OR.
- Add one tier 2 query function (module location decided in design.md) that
  looks up a sender's `contact_key` against the existing
  `contact_stats`/`contact_reciprocity` views and returns the reply-signal
  fields ("have I ever replied to this sender, how recently, how often").
  Not wired into any UI — Block C's triage inbox, the eventual consumer,
  doesn't exist yet.

## Capabilities

### New Capabilities
- `noise-parser-tier-1-2`: deterministic and relational noise signals for
  the ingest/query layer, ahead of the (still-blocked) semantic tier 3

### Modified Capabilities
(none — no existing spec file covers this)

## Impact

- `adapters/store_writer.py`: `upsert()`'s INSERT statement gains
  `is_automated`.
- `adapters/outlook/sync.py`: `_to_envelope` gains the remaining tier 1
  signals.
- New: a tier 2 query function (home TBD in design.md).
- No changes to WhatsApp or LinkedIn adapters — tier 1's remaining signals
  are meaningless for those channels (no email headers/domains).
- No changes to Block C (triage inbox doesn't exist yet) or to tier 3 (still
  blocked on Mark's model API decision).
