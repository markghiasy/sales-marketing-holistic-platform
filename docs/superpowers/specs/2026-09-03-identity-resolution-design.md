# Identity Resolution (§8) — Design

**Date:** 2026-09-03
**Status:** Approved by Eva, pending implementation plan

## Problem

`identity.person_id` has been null on every row since Block A — nothing
has ever populated it. Without it, the same real person shows up as
separate, unconnected rows across Outlook/WhatsApp/LinkedIn, and §10's
network graph (already built, already grouping by
`coalesce(identity.person_id, identity.id)`) can only rank handles, not
people. This is Eva's own scoping decision to make (delegated by Mark:
"must be reasonable and she has to be able to explain it to him" — not
a request to build the maximum possible thing), grounded directly in
§8's actual text rather than reconstructed from memory.

**§8's own framing, worth repeating exactly:** "The failure that matters
is merging two different people. It quietly corrupts the graph, and by
tier 3 it could put one person's private context into a message drafted
to another. So: optimise for precision, accept low recall early." And:
"Zero false merges, plus a visible review queue for the ambiguous
cases. An engine that confidently merges everything is worse than one
that resolves half and tells you honestly which half it wasn't sure
about."

## Scope

Build all six rules of §8's ladder in one pass (v1 automatic rules +
v2's LinkedIn correlation + review queue), not split across two builds:

1. Exact normalised email match — automatic
2. Exact normalised phone match — automatic
3. Contact record linking an email to a phone number (the "bridge") —
   automatic
4. Phone number found in an email signature — high confidence, but
   still queued for review, not auto-applied (§8's own wording: "high
   confidence; review before auto-linking")
5. LinkedIn name + organisation correlation — never automatic, always
   queued for review, low confidence
6. Everything else stays unresolved — not a rule to implement, the
   absence of one

**Known real-data limitation, worth stating plainly rather than
discovering later:** this account's `graph_contact` table (the Outlook
Contacts folder, ingested in Block A) is currently empty — confirmed by
directly probing `/me/contacts`, not assumed. This is because this
mailbox authenticates through Microsoft's `consumers` endpoint (see
`adapters/outlook/client.py`'s `TOKEN_URL`) — a personal Microsoft
account, not one backed by a real organisation's directory — and it has
never been used as anyone's actual day-to-day inbox, so nobody ever
saved a contact to it. Rules 2 and 3 both depend on this table and will
match zero candidates on this account today. This isn't a bug in the
matching logic — it's this specific account's real history — and the
mechanism should work as intended once Phase 2 points it at Mark's real,
lived-in Outlook account. Explicitly not in scope for this build:
backfilling contacts from any other source (e.g. Gmail) into
`graph_contact` to work around this — Phase 1's whole purpose is
proving the mechanism, not manufacturing realistic data for a throwaway
test account.

## Architecture

A new, independent module, `adapters/resolution/` — not a peer of the
Outlook/WhatsApp/LinkedIn adapters in the sense of talking to an
external API; it only reads what's already in the store and writes
back `identity.person_id` / `person` / `link_candidate` rows. No network
calls, no rate limits, cheap to run.

```
adapters/resolution/
  run.py                  — entrypoint: python -m adapters.resolution.run
  rules.py                — Rules 1-4
  linkedin_correlation.py — Rule 5
  naming.py               — person.primary_name / preferred_name selection
```

Run manually for now (`python -m adapters.resolution.run`), not on a
schedule — deliberately: unlike the channel syncs, there's no time-
sensitive reason new data must be resolved within minutes, and adding
scheduling now would be optimising before there's any real usage
pattern to optimise for. Revisit once this has actually been run a few
times.

**Review queue** — added to the existing ops dashboard
(`scripts/onboarding/app.py`, `scripts/onboarding/templates/index.html`)
rather than a new tool, reusing infrastructure that already exists
rather than standing up something separate for one more page:
- `GET /resolution` — a page listing every `link_candidate` with
  `status = 'pending'`, sorted by `score` descending, each row showing
  both identities' channel, handle, and display name side by side, plus
  which rule produced it.
- `POST /resolution/<id>/confirm` — merges: creates a `person` row if
  neither identity already has one (or reuses one identity's existing
  `person_id` if it has one), sets `identity.person_id` on both sides,
  sets `link_candidate.status = 'confirmed'`.
- `POST /resolution/<id>/reject` — sets `status = 'rejected'`, no
  further effect. Never deletes the candidate row — the record of "this
  was proposed and rejected" is itself useful (stops the same wrong
  candidate from silently resurfacing if the rule runs again).

## Rule-by-rule design

**Rule 1 — exact email match (automatic).** Compares Outlook
`identity.handle` (already normalised: lowercased email) against
`linkedin_connection.email` (populated on ~2.7% of rows — sparse by
LinkedIn's own design, not a bug). A match sets `identity.person_id` on
both the Outlook and the matching LinkedIn identity directly — no
`link_candidate` row, because an exact email match is unambiguous by
construction (this is what "automatic" means throughout this ladder).

**Rule 2 — exact phone match (automatic).** Compares WhatsApp
`identity.handle` (E.164 phone) against `graph_contact.phones[]`
(digits-only, per that table's own normalisation). A match links the
WhatsApp identity to whichever *other* identity that contact record's
owner is already resolved to, if any — on its own, a bare phone match
in a contacts record doesn't carry a name-worthy signal past what's
already in `identity.display_name`. Zero matches expected today (see
Known real-data limitation above).

**Rule 3 — the contact bridge (automatic).** The strongest signal in
the ladder: a single `graph_contact` row whose `emails[]` contains an
Outlook identity's handle *and* whose `phones[]` contains a WhatsApp
identity's handle. Both identities resolve to the same person
immediately — this one record is direct, first-party evidence they're
the same human, no fuzzy matching involved. Zero matches expected today
(see Known real-data limitation above).

**Rule 4 — phone number in an email signature (queued, high score).**
Scans `message.body_text` for phone-number-shaped substrings in
messages sent by each Outlook identity (own outbound mail only —
scanning inbound mail risks picking up someone else's number quoted in
a reply chain), checks each candidate number against WhatsApp
identities' handles after the same digits-only normalisation
`graph_contact.phones[]` uses. A match writes a `link_candidate` with a
high `score` (distinct band from Rule 5's, so the review queue's
ordering makes the confidence difference visible at a glance) and
`method = 'email_signature_phone'` — queued, not auto-applied, exactly
matching §8's own wording ("high confidence; review before
auto-linking").

**Rule 5 — LinkedIn name + organisation correlation (queued, low
score).** Compares `linkedin_connection.first_name`/`last_name`/
`company` against Outlook and WhatsApp identities' `display_name`,
using a name-similarity check (exact-normalised match scores highest;
a looser similarity — e.g. matching first name + last initial, or
handling common nickname forms — scores lower but still queues,
consistent with "never automatic" regardless of how close the match
looks). Writes `link_candidate` with `method = 'linkedin_name_company'`
and a low `score`, always below Rule 4's band.

**Rule 6 — everything else.** Not code — the natural result of nothing
above matching. `identity.person_id` stays null, which the schema and
§10's graph views already treat as a valid, expected state (an
unresolved identity just doesn't merge into anyone else's row).

## Naming a merged person

`person.primary_name` and a new nullable `person.preferred_name` column
(this build's one schema change — a new migration,
`db/migrations/0005_person_preferred_name.sql`) are chosen from the set
of `display_name` values across every identity being merged:

- Filter to names that look like real names, not a handle/username —
  multi-word, capitalised tokens score as "name-like"; a single
  lowercase word, anything containing digits or underscores, or a
  display name that's just the raw handle repeated (some channels fall
  back to this) does not.
- `primary_name` = the longest name-like candidate.
- `preferred_name` = the shortest *different* name-like candidate, if
  one exists (e.g. Outlook shows "Eric Tham", WhatsApp shows "Eric" →
  `primary_name = "Eric Tham"`, `preferred_name = "Eric"`). If there's
  only one name-like candidate, or all of them are identical,
  `preferred_name` stays null — there's no real "usual name" signal to
  record.
- If nothing looks name-like, fall back to a straight channel priority
  (Outlook > LinkedIn > WhatsApp display_name, whichever exists),
  `preferred_name` left null.

This is a best-effort heuristic, not a guarantee — it will occasionally
pick a genuine short-form legal name (e.g. "Eric" as someone's real,
complete first name) as `preferred_name` when it's actually their
`primary_name`. Acceptable given §8's own precision-over-recall stance
applies to *merging*, not to this secondary naming question — a
slightly-off preferred name is cosmetic, not a data-integrity risk.

## Data flow

No new tables beyond the one column added to `person`. Every rule
reads from tables that already exist and are already populated by
Block A's adapters (`identity`, `graph_contact`, `linkedin_connection`,
`message`). `link_candidate` already exists in the schema from the
very first migration and has never been written to until now.

## Error handling

- A rule finding zero candidates is a normal, expected outcome (see
  Rules 2/3 above) — not an error, no special handling needed.
- `run.py` processes rules independently; one rule raising doesn't
  block the others (a name-similarity bug in Rule 5 shouldn't prevent
  Rule 1's exact-match pass from completing) — each rule wrapped in its
  own try/except, logged, continue to the next.
- The confirm/reject routes validate the candidate is still `pending`
  before acting (a candidate confirmed or rejected twice — e.g. two
  browser tabs — should be a no-op on the second click, not a crash or
  a double-merge).

## Testing

TDD throughout, matching this project's existing pattern — every rule
gets tests against constructed fixture data (fake identities, fake
contact records, fake message bodies) proving the matching logic itself
is correct, written and passing before the rule is considered done.
Additionally, after the automatic rules are built, run `python -m
adapters.resolution.run` against this project's real (if currently
contact-sparse) database and inspect the actual output by hand — not
skipped just because the known real-data limitation means Rules 2/3
won't produce anything to show; Rule 1 (LinkedIn connections' sparse
emails) and Rule 4 (email-signature phone scan against real message
bodies) both have real data to run against today and should be checked
against it, not just unit tests.
