# Identity Resolution + Knowledge Graph (§8 / §10) — Design

**Date:** 2026-09-03
**Status:** Approved by Eva, pending implementation plan

## Problem

`identity.person_id` has been null on every row since Block A — nothing
has ever populated it. Without it, the same real person shows up as
separate, unconnected rows across Outlook/WhatsApp/LinkedIn, and §10's
network graph (already built, already grouping by
`coalesce(identity.person_id, identity.id)`) can only rank handles, not
people.

Separately, Mark asked (2026-08-21) for §10's graph to grow beyond
message-volume ranking into a real knowledge graph — entities,
relationships, and facts extracted from message content (his own
example: recording that two contacts have a boss/subordinate
relationship). That's Eva's own scoping decision to make ("must be
reasonable and she has to be able to explain it to him" — not a request
to build the maximum possible thing).

**Why these two are one design, not two.** Identity resolution and
knowledge-graph extraction are different responsibilities but they run
against the same messages and need the same kind of output: a claim,
with evidence and a confidence level, that a human can confirm or
reject. Building two separate pipelines — one that decides "these two
identities are the same person," another that decides "this person
works at that company" — means writing the same
extract-evidence-review-confirm machinery twice. This design shares it
once.

**§8's own framing on the identity side, worth repeating exactly:**
"The failure that matters is merging two different people. It quietly
corrupts the graph, and by tier 3 it could put one person's private
context into a message drafted to another. So: optimise for precision,
accept low recall early." And: "Zero false merges, plus a visible
review queue for the ambiguous cases. An engine that confidently merges
everything is worse than one that resolves half and tells you honestly
which half it wasn't sure about." The same standard applies to
knowledge-graph facts: a wrong "reports to" guess is exactly the kind
of error this project has already built a correction mechanism for
elsewhere (see `action`'s `verdict` column) — facts get the same
treatment, not a lighter one just because they're new.

## Scope

**Phase 1 — rule-based, no model calls, buildable now.**
1. Exact normalised email match — automatic
2. Exact normalised phone match — automatic
3. Contact record linking an email to a phone number (the "bridge") —
   automatic
4. Phone number found in an email signature — high confidence, but
   still queued for review, not auto-applied (§8's own wording: "high
   confidence; review before auto-linking")
5. LinkedIn name + organisation correlation, via plain string
   similarity — never automatic, always queued for review, low
   confidence
6. Everything else stays unresolved — not a rule to implement, the
   absence of one
7. Knowledge-graph facts from structured sources that are already
   fully ingested and need no model call: `linkedin_connection.company`
   / `.position` become `WORKS_AT` / `HAS_TITLE` facts directly.

**Phase 2 — model-assisted, blocked on Mark approving a commercial
model API account and budget (§13 rule 3, §15).** Not started until
that call happens:
8. Rule 5's matching quality improved by a model call comparing name/
   company pairs (still queued for review regardless of the model's
   confidence — this doesn't loosen "never automatic," it only changes
   what produces the candidate).
9. Knowledge-graph facts extracted from message content itself
   (`REPORTS_TO`, `INTRODUCED_BY`, `MEMBER_OF`, project-related facts)
   — the kind of fact no regex or structured field can produce.

Phase 1 has no external dependency and needs no one's sign-off beyond
this design. Phase 2 is real, separately-scoped work gated on a
decision that isn't Eva's or Claude's to make — see "The model-API
question" below.

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
mechanism should work as intended once Phase 2 (of the *project's*
phases, not this design's — cutover) points it at Mark's real,
lived-in Outlook account. Explicitly not in scope for this build:
backfilling contacts from any other source (e.g. Gmail) to work around
this — the whole point of building on a throwaway test account is
proving the mechanism, not manufacturing realistic data for it.

## The Neo4j question — decided, not deferred

An earlier draft of this design considered Neo4j (or another dedicated
graph database) for the knowledge-graph facts. **Decided against.**
Two reasons, not one:

1. Mark's own §10 text names "no separate graph store" as one of only
   four choices he explicitly defends in the brief: "`message_participant`
   IS the graph... no separate graph store." Introducing one now
   reverses a decision Mark made and defended in writing — that's a
   call for Mark to make, not something to change unilaterally the way
   the knowledge-graph *content* scope was explicitly delegated.
2. Real, current costs: every extra piece of infrastructure multiplies
   the redeploy burden §2/§5 already name as a first-class constraint
   ("deploying a clean second instance is a gate at every block
   checkpoint," "no dependency on your machine," two separate
   deployments never merged) — and keeping a second database in sync
   with Postgres (what happens when a merge lands in one but the sync
   to the other fails or lags?) is ongoing engineering work that
   doesn't exist with one store. Graph databases earn that cost at
   scale, or when the query *model* (multi-hop traversal expressed
   natively) is doing real work a relational engine can't express
   reasonably — worth being honest that scale alone isn't the whole
   argument, but the facts this design needs
   (`WORKS_AT`/`REPORTS_TO`/`MEMBER_OF`/`INTRODUCED_BY`, a few hundred
   people, a few thousand edges) are comfortably expressible as rows
   plus recursive CTEs when a multi-hop query is genuinely needed.

If real usage later surfaces a graph query need Postgres genuinely
can't serve well, that's a concrete case to bring back to Mark — not a
default to build around now.

## Architecture

```
LinkedIn / Outlook / WhatsApp adapters (existing, unchanged)
        │
        ▼
   PostgreSQL (existing store)
        │
        ▼
adapters/resolution/           — Phase 1, no model calls
  run.py                       — entrypoint: python -m adapters.resolution.run
  rules.py                     — Rules 1-4, safety checks, conflict detection
  linkedin_correlation.py      — Rule 5 (string similarity in Phase 1)
  structured_facts.py          — WORKS_AT/HAS_TITLE from linkedin_connection
  naming.py                    — person.primary_name / preferred_name
        │
        ▼ (Phase 2, once approved)
adapters/resolution/
  extraction.py                — one model call per thread, shared by
                                  Rule 5's quality improvement AND
                                  message-content fact extraction;
                                  structured JSON output, closed
                                  vocabulary of fact types
        │
        ▼
  link_candidate (identity)         fact (knowledge graph)
        │                                 │
        └──────────────┬──────────────────┘
                        ▼
        ops-dashboard review queue (both types, one page)
                        │
                        ▼
        identity.person_id / person   +   confirmed facts
```

Phase 1 runs manually for now (`python -m adapters.resolution.run`),
not on a schedule — deliberately: unlike the channel syncs, there's no
time-sensitive reason new data must be resolved within minutes, and
adding scheduling now would be optimising before there's any real usage
pattern to optimise for. Revisit once this has actually been run a few
times.

## Shared extraction, Phase 2 only

The one thing Phase 2 does that Phase 1 doesn't: a single model call
per thread produces structured *observations* — not a merge decision,
not a confirmed fact, just "here's what this thread seems to say,"
consumed by both identity resolution and fact extraction rather than
run as two separate model passes over the same text. Example, from
§10's own illustrative style:

> "Hi Eva, Sam here from Acme. Mark suggested I reach out. I lead their
> data team."

produces observations roughly like: sender has-name "Sam", sender
works-at "Acme", sender has-role "Data Lead", sender referred-by
"Mark" — each with a confidence and the source span. Rule 5 uses the
name/company observations to score identity candidates better than
plain string similarity; fact extraction turns the relationship
observations into `fact` rows. Neither consumer trusts the output
directly — see "Facts require provenance" below.

**Cost control, reusing this project's own established pattern.** §9's
noise parser already states the policy this should follow: "classifying
a thread that closed in 2019 costs real money and tells us nothing...
run tier 3 only on recent mail and forward." Phase 2 extraction applies
the same rule — only threads not yet processed (tracked via a new
`extraction_run` table keyed on thread id, so re-running the pipeline
never re-bills for a thread already looked at), and only recent/active
threads, not the full historical backfill. One call per thread, not
per message, matching §11's own reasoning for why task extraction runs
at thread level ("a commitment usually spans a few messages, and the
thread is the unit that carries enough context").

**Closed vocabulary, not open-ended extraction.** The model's output is
constrained to a fixed, small set of fact types — not free-form
relationship labels it invents per message:
`works_at`, `has_title`, `reports_to`, `colleague_of`, `referred_by`,
`member_of` (project), `located_in`. Anything the model wants to
express outside this set is dropped, not stored as a novel type — an
unbounded vocabulary is exactly the "huge enterprise ontology" §10's
own spirit (and the earlier declined proposal's own principle 9 — "do
not build a huge enterprise ontology") warns against.

## The model-API question

Phase 2 needs a commercial model API account (§13 rule 3 permits this —
it bars consumer chat interfaces and free tiers, not commercial API
terms that exclude training) and a budget, which is Mark's call and his
payment per §15 ("aggregator, Notion and model API accounts — tell me
what you need and what it costs, I pay for them, not you"). Real
numbers to bring to that conversation, queried directly rather than
estimated: **4,517 Outlook threads, 324 LinkedIn threads, 125 WhatsApp
threads** as of 2026-09-03. Applying the "recent/forward only" policy
above means the real call volume is much smaller than that full count
— worth pricing out once a recency window is agreed, not before.

Whether comparing short name/company strings for Rule 5 counts as
"comms content" under §13 rule 3 is a genuine reading question, not
something to guess past — it's a much smaller, lower-sensitivity ask
than full message-content extraction (no message body ever leaves the
system for Rule 5's use case), so it's reasonable to ask Mark to
approve it separately/first if the full extraction piece needs more
deliberation.

## Safety checks that apply across every identity rule

Three ideas taken from an externally-sourced architecture proposal
Eva reviewed and largely declined (it also proposed Splink probabilistic
matching, a separate evidence-graph system, and Neo4j — all declined;
see "The Neo4j question" above and the Splink note below). These three
are genuinely cheap and apply across every rule, so they're specified
once here rather than repeated per rule:

**1. Shared/generic identifiers never auto-merge.** An exact match on a
role address (`support@`, `info@`, `admin@`, `sales@`, `team@`,
`reception@`, `noreply@`, `contact@`, `hello@`, `office@`) or on a
switchboard/shared phone is not evidence that two identities are the
same person — several different humans legitimately sit behind one. Any
rule matching on such an identifier writes a `link_candidate` for
review instead of merging, regardless of how exact the match is.

**2. Implausible cluster size blocks the merge.** If applying a
candidate merge would attach an unreasonable number of distinct
identities to one person (e.g. a shared office number bridging a dozen
separate people), that's a signal the identifier itself is shared
rather than personal. Detected by counting how many identities a merge
would place under one `person_id`; above a configurable threshold, the
merge is refused and queued for review rather than applied.

**3. A human rejection is durable.** `link_candidate.status =
'rejected'` means "a human looked at this and said no" — re-running the
rules must not re-propose the same identity pair. Every rule checks for
an existing rejected candidate on the same pair before writing a new
one, and never auto-merges a pair a human has already rejected. The
same durability applies to rejected `fact` rows once Phase 2 exists.

**4. Conflict detection, using the tables that already exist.** Some
contradictions are worth catching before merging, and all of them are
answerable with SQL over `identity`/`link_candidate` — no separate
evidence-graph system, consistent with §10's own "the graph is a view
over the store, not a separate system" framing:
- The same identity being pointed at two different `person_id`s by two
  different rules in one run — a genuine contradiction; neither merge
  is applied automatically, both go to review.
- A merge that would place two identities on the *same channel with
  different handles* under one person where that's implausible (e.g.
  two distinct active LinkedIn profile URLs) — queued, not applied.

**No Splink.** It's a real, capable tool for probabilistic record
linkage, but it earns its complexity at a scale (tens of thousands to
millions of records with no shared key) this project doesn't have —
its m/u match-probability parameters need enough data to estimate
meaningfully, and a few hundred identities won't produce numbers more
trustworthy than the explicit rules above, while being much harder to
explain to Mark than "this rule matched because X."

## Evidence provenance on every candidate and fact

`link_candidate` currently records `method` (which rule fired) but not
*what the rule actually saw*. This build adds a `reason` column (text)
recording the concrete evidence in human-readable form:

- Rule 4: which message the number was found in, and the matched
  number (e.g. "phone +61400000000 found in signature of message sent
  2026-08-14, matches WhatsApp handle 61400000000")
- Rule 5: the two names and the company that correlated, plus the
  similarity that triggered it
- Any rule blocked by a safety check above: which check blocked it and
  why (e.g. "exact email match on support@acme.com — generic role
  address, not merged automatically")

The new `fact` table (Phase 1 schema, populated by Phase 1's
structured-source facts immediately and by Phase 2's extraction later)
follows the same provenance pattern this project already uses for
`action`/`outreach` — `confidence`, `model`, `prompt_version`,
`verdict`, `verdict_at` — because a wrong extracted fact needs the same
correction path a wrong extracted task already has, not a new one:

```
fact
  id, subject_person_id, fact_type, object_text, object_person_id (null unless the object is also a person)
  confidence, source, source_message_id
  status                -- 'pending' | 'confirmed' | 'rejected', same states as link_candidate
  reason                -- human-readable evidence, same spirit as link_candidate.reason
  model, prompt_version  -- null for Phase 1's structured-source facts, populated once Phase 2 exists
  extracted_at
```

This is also what makes both the naming and the fact decisions
explainable to Mark later, which §15's delegation explicitly requires.

## Rule-by-rule design (identity)

**Rule 1 — exact email match (automatic).** Compares Outlook
`identity.handle` (already normalised: lowercased email) against
`linkedin_connection.email` (populated on ~2.7% of rows — sparse by
LinkedIn's own design, not a bug). A match sets `identity.person_id` on
both the Outlook and the matching LinkedIn identity directly — no
`link_candidate` row, because an exact email match is unambiguous by
construction (this is what "automatic" means throughout this ladder).

**Rule 2 — exact phone match (automatic).** Compares WhatsApp
`identity.handle` (E.164 phone) against `graph_contact.phones[]`
(digits-only, per that table's own normalisation). Zero matches
expected today (see Known real-data limitation above).

**Rule 3 — the contact bridge (automatic).** A single `graph_contact`
row whose `emails[]` contains an Outlook identity's handle *and* whose
`phones[]` contains a WhatsApp identity's handle resolves both
identities to the same person immediately — direct, first-party
evidence, no fuzzy matching. Zero matches expected today (see Known
real-data limitation above).

**Rule 4 — phone number in an email signature (queued, high score).**
Scans `message.body_text` for phone-number-shaped substrings in
messages sent by each Outlook identity (own outbound mail only —
scanning inbound mail risks picking up someone else's number quoted in
a reply chain), checks each candidate number against WhatsApp
identities' handles after the same digits-only normalisation
`graph_contact.phones[]` uses. Writes a `link_candidate` with a high
`score` (distinct band from Rule 5's) and `method =
'email_signature_phone'` — queued, not auto-applied, exactly matching
§8's own wording.

**Rule 5 — LinkedIn name + organisation correlation (queued, low
score in Phase 1, quality-improved in Phase 2).** Phase 1: plain
string-similarity comparison of `linkedin_connection.first_name`/
`last_name`/`company` against Outlook and WhatsApp identities'
`display_name`. Phase 2: the same comparison, but scored with model
assistance for nickname/company-variant handling — still always
queued, never automatic, at either phase. `method =
'linkedin_name_company'`, score always below Rule 4's band.

**Rule 6 — everything else.** Not code — the natural result of nothing
above matching. `identity.person_id` stays null, which the schema and
§10's graph views already treat as a valid, expected state.

## Naming a merged person

`person.primary_name` and a new nullable `person.preferred_name` column
are chosen from the set of `display_name` values across every identity
being merged:

- Filter to names that look like real names, not a handle/username —
  multi-word, capitalised tokens score as "name-like"; a single
  lowercase word, anything containing digits or underscores, or a
  display name that's just the raw handle repeated does not.
- `primary_name` = the longest name-like candidate.
- `preferred_name` = the shortest *different* name-like candidate, if
  one exists (e.g. Outlook shows "Eric Tham", WhatsApp shows "Eric" →
  `primary_name = "Eric Tham"`, `preferred_name = "Eric"`). If there's
  only one name-like candidate, or all are identical, `preferred_name`
  stays null.
- If nothing looks name-like, fall back to channel priority (Outlook >
  LinkedIn > WhatsApp display_name), `preferred_name` left null.

Best-effort, not a guarantee — it will occasionally pick a genuine
short-form legal name as `preferred_name` when it's actually the
complete name. Acceptable given §8's precision-over-recall stance
applies to *merging*, not this secondary naming question — a
slightly-off preferred name is cosmetic, not a data-integrity risk.

## Review queue

Added to the existing ops dashboard (`scripts/onboarding/app.py`,
`scripts/onboarding/templates/index.html`) rather than a new tool —
one page, both candidate types, not two separate review surfaces:

- `GET /resolution` — lists every `link_candidate` with
  `status = 'pending'` (identity merges) and every `fact` with
  `status = 'pending'` (Phase 2 onward), sorted by score/confidence
  descending, each row showing the evidence (`reason`) plainly.
- `POST /resolution/candidate/<id>/confirm` — merges: creates a
  `person` row if neither identity already has one (or reuses one
  identity's existing `person_id`), sets `identity.person_id` on both
  sides, sets `status = 'confirmed'`.
- `POST /resolution/candidate/<id>/reject` — sets `status = 'rejected'`.
  Never deletes the row.
- `POST /resolution/fact/<id>/confirm` / `.../reject` — same shape,
  for `fact` rows once Phase 2 exists.

## Data flow

No new tables in Phase 1 beyond `fact` (which exists from Phase 1 to
carry the structured-source facts, ready for Phase 2 to populate
further) — plus two added columns (`person.preferred_name`,
`link_candidate.reason`), in one migration,
`db/migrations/0005_identity_resolution.sql`. Every Phase 1 rule reads
from tables that already exist and are already populated by Block A's
adapters (`identity`, `graph_contact`, `linkedin_connection`,
`message`).

## Error handling

- A rule finding zero candidates is a normal, expected outcome — not
  an error.
- `run.py` processes rules independently; one rule raising doesn't
  block the others — each wrapped in its own try/except, logged,
  continue to the next.
- The confirm/reject routes validate the row is still `pending` before
  acting — a double-click or two tabs should be a no-op on the second
  action, not a crash or a double-merge.

## Testing

TDD throughout. **Adversarial tests are the point, not an extra** —
§8's stated failure mode is merging two different people, so the tests
that matter most are the ones where records *look* like a match and
must not be merged:
- Two different people with the same full name at the same company
- Two different people sharing a corporate role address
- Two different people sharing an office switchboard number
- A recycled phone number now belonging to someone else
- Two similarly-named LinkedIn profiles at the same company
- One weak bridge connecting two otherwise-distinct clusters
- Transitive over-merge: A matches B, B matches C, but A and C are
  demonstrably different people — the merge must not chain through

A passing implementation is one where these all stay unmerged, not one
that resolves the most identities.

After Phase 1's automatic rules are built, run `python -m
adapters.resolution.run` against this project's real (if currently
contact-sparse) database and inspect the output by hand — Rule 1
(LinkedIn connections' sparse emails) and Rule 4 (email-signature phone
scan against real message bodies) both have real data to run against
today.
