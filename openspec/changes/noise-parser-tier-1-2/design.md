## Context

§9's noise parser has three tiers, cheapest first: tier 1 (deterministic,
free), tier 2 (relational, effectively free — "a SQL query"), tier 3
(semantic, real money, blocked on Mark's model API decision). Only tier 1's
Graph-classification signal exists today
(`adapters/outlook/sync.py`'s `_to_envelope`); the rest of tier 1, all of
tier 2, and the `is_automated` persistence bug found during explore are all
open.

## Goals / Non-Goals

**Goals:**
- `message.is_automated` reflects reality after ingest (fixes the silent
  `store_writer` bug).
- Tier 1 implements all four signals §9 names: Graph classification (already
  done), List-Unsubscribe header, no-reply/bulk sender pattern, known
  automated domain.
- Tier 2 exposes a reply-signal lookup by contact, built on the existing
  `contact_stats`/`contact_reciprocity` views rather than new schema.

**Non-Goals:**
- No triage inbox or any UI — Block C, not this change.
- No WhatsApp/LinkedIn changes — tier 1's remaining signals need email
  headers/domains, which neither channel has.
- No tier 3 / model calls — still blocked on Mark.
- No attempt to make the automated-domain seed list exhaustive or
  data-verified — real mailbox data wasn't available while designing this
  (local Postgres was down); ship a documented, reasonable starting list and
  flag it for verification once run for real, matching how Rule 1/4 in the
  identity-resolution work were treated.

## Decisions

**Tier 1's remaining signals go directly into `_to_envelope`, not a shared
module.** Alternative considered: a generic `adapters/noise_parser.py`
tier-1 function taking headers/from_handle, callable by any adapter.
Rejected — List-Unsubscribe headers and email domains only exist for
Outlook; WhatsApp handles are phone numbers, LinkedIn handles are member
ids, and §3 fixes the channel count at three with no fourth ever. There is
no second caller today, so the abstraction has nothing to generalize over;
YAGNI. If a future channel genuinely needs equivalent logic, extract then.

**Multiple tier-1 signals combine with OR.** Any one of {Graph
classification == "other", List-Unsubscribe header present, sender
local-part/domain matches a known pattern} sets `is_automated = True`. No
weighting or scoring — §9 frames tier 1 as a binary, high-confidence filter
("catches most of the volume... free"), not a graded signal like tier 2/3.

**Sender-pattern matching, concretely:**
- Local-part patterns (case-insensitive, matched against the part before
  `@`): `noreply`, `no-reply`, `donotreply`, `do-not-reply`, `notifications`,
  `notification`, `alerts`, `alert`, `mailer-daemon`, `postmaster`. This
  reuses the same spirit as the identity-resolution design's generic-role
  address list, but a different list — these are automated-sender signals,
  not shared-mailbox signals, so they don't get merged with that list even
  though some strings could theoretically overlap; the two lists mean
  different things and evolve independently.
- Domain list: a small seed set of common transactional/ESP domains (e.g.
  `sendgrid.net`, `mailgun.org`, `amazonses.com`, `mailchimp.com`,
  `notifications.google.com`) kept as a plain Python set/list in
  `adapters/outlook/sync.py`, next to the existing tier-1 code, not a config
  file or DB table — it's a handful of entries, versioned in git like the
  rest of the parsing logic, and easy to extend with a one-line diff once
  real mailbox data suggests additions.

**List-Unsubscribe detection reuses the header list already being
fetched.** `_resolve_sent_at` already reads `raw["internetMessageHeaders"]`
for the `Date` header — the same list gets scanned for a header named
`list-unsubscribe` (case-insensitive), presence-only check, no need to parse
the header's own mailto:/https: contents. No new Graph `$select` fields or
scopes required.

**Tier 2 gets its own module: `adapters/reply_signal.py`.** Unlike tier 1,
this is genuinely channel-agnostic (operates on `contact_key`, post-ingest,
same grouping the §10 views already use — `coalesce(identity.person_id,
identity.id)`), not embedded in any one adapter's parsing code. One
function:

```python
def reply_signal(cur, contact_key: str) -> ReplySignal:
    # queries contact_stats + contact_reciprocity for this contact_key
    # returns sent_count, received_count, reciprocity_ratio, last_contact_at
    # (None fields when the contact has no message history at all)
```

No new SQL — a straightforward join/select against the two existing views.
Not called from anywhere yet (no UI exists to call it); it's infrastructure
for Block C.

**The `is_automated` INSERT fix is a one-line addition to
`store_writer.upsert()`'s existing column list and value tuple** — no
schema change (the column and its default already exist), no migration
needed.

## Risks / Trade-offs

- **[Risk]** The seed domain/pattern lists are guesses, not measured against
  this mailbox's real automated senders. → **Mitigation**: run tier 1
  against real ingested mail after merging (same verification step used for
  Rule 1/4) and inspect what it catches/misses by hand; extending the list
  is a one-line change, not a design change.
- **[Risk]** `store_writer`'s fix changes `is_automated` for every message
  re-ingested or newly ingested from this point forward — a real behavior
  change, not just a bug fix in isolation, since anything reading
  `is_automated` downstream (none yet, but future Block C code will) now
  sees real values instead of always-false. → Acceptable: nothing downstream
  reads this field yet, so there's no risk of breaking an existing consumer;
  worth stating so it isn't mistaken for a no-op fix later.
- **[Trade-off]** Tier 2's function has no caller yet, so it can't be
  verified against real usage patterns until Block C exists — only unit-
  testable against the view data directly. Accepted; matches Block B's
  scope (build tiers 1/2, not the inbox that consumes them).

## Migration Plan

No database migration — `is_automated` and the tier-2 views already exist.
Pure code changes: `store_writer.py`, `outlook/sync.py`, new
`reply_signal.py`. No rollback complexity beyond a normal revert.

## Open Questions

None outstanding — module boundaries, signal combination, and scope were
all resolved during explore mode with Eva.
