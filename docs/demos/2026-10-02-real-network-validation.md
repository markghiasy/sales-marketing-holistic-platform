# Real Network trial — acceptance record

30 September 2026. Runtime revision: `1d5e93f` (functional fixes through
`356a7e1`, followed by lint and CI setup). Prepared for a controlled local trial.
Mac execution is pending. This is not a claim of general production readiness.

## What was verified

- Eva's source:7,343 messages,2,342 identities,73 canonical people,5,015 threads,
  731 organizations,1,784 facts,922 LinkedIn connection snapshots,eight hidden
  contacts and13 self aliases. These are source counts, not verified skills.
- A separately bound `network` schema and restricted writer were initialized.
  The corrected first backfill published version1. Source business tables and
  existing collectors were not migrated or restarted.
- **579 tests passed in237.81s** after the final lint changes. Full coverage
  includes PostgreSQL transactions, updates/replay/deletion, merge reversal,
  hidden contacts, interrupted snapshots, outage/recovery, reviews, bounded
  retrieval, delayed-model corrections, unrelated-new-message controls and UI.
- A fresh whole-branch review found three Important issues. All were fixed:
  entity-only extraction stays reviewable; citations load three at a time and
  fail independently; the Flask minimum enforces the trusted-host boundary.
  UUID-based message sampling was regraded as Important and fixed using recent
  messages with a historical cutoff. Full [decision record](2026-10-02-trial-decisions.md).
- Current Ruff checks passed. CI now installs the Edge runtime used by UI tests.
- A clean Windows archive installed in an independent virtual environment;
  the final archive installed with pip exit0 and passed dependency, runtime-resource
  and all four missing-config CLI checks, as recorded in the delivery record.
  Source-checkout assets/SQL are required; wheel-only deployment is unsupported.
- Real browser interaction succeeded in21.204s through graph, contact selection
  and first citation, with no page errors, no synthetic banner and exactly three
  citation requests after clicking. This is one run, not a UI latency percentile.

## Real request measurements

Updated candidate:loopback port5059, fresh version1,50 displayed nodes,26 edges,
ten sampled contacts,two version-bound citations. The view reports truncation.

| Route | One observed request |
|---|---:|
| Health |1.014s|
| Graph |5.647s|
| Ten-contact sample |5.053s|
| Conversation |3.038s|
| Name search |6.324s|
| Individual citations |6.893s /6.847s|

The latest real strategy query returned HTTP200 in **76.995s**:three cited
findings,four distinct sources,three unresolved gaps and a fifteen-node subgraph.
`claude-haiku-4-5-20251001` used17,125 input/1,068 output tokens and a27,687-byte
pack (28,000-byte cap). **Strategy responses are still slow.** This trial has no
subsecond or fixed-latency promise, and citations still incur source validation.

Earlier same-question runs took232.898s and98.381s, with different generated
plans. They are observations, not a controlled end-to-end speedup claim. The
98.381s profile measured model stages8.430/18.342s and evidence packing28.550s;
DB work and source validation also contribute materially.

A controlled comparison on the **same captured real slice and requirements**
produced identical packs:6.1874s before versus0.0561s after caching unchanged
lexical signals,110 candidates,27,427bytes. Twelve additional fictional
focus/history/path/budget combinations matched exactly. This is an engineering
optimization, not evidence of improved retrieval quality or a novel algorithm.

One explicitly selected real source was sent for extraction:27.135s,
2,465 input/38 output tokens. It produced an empty batch, and nothing was
confirmed. Positive extraction/confirmation/rejection/restart cases passed with
fictional sources. The empty real result is not proof of all extraction semantics.

## Fictional scale measurements

Guarded local PostgreSQL, short messages, one thread; no real source content.
Each measured retrieval returned nonempty evidence. Context preparation is
included; LLM generation and hosted-database latency are excluded.

| Workload | Backfill | First | Median | p95 | Largest pack |
|---|---:|---:|---:|---:|---:|
|24,222 messages,2,000 identities,balanced direct messages,10 queries (`5edcf16`)|81.750s|1.360s|1.341s|1.410s|27,492B|
|48,000 messages,3,000 identities,80% concentrated on one author,four participants/message,6 queries (before packing optimization)|207.501s|2.317s|2.255s|2.464s|27,302B|

The sample query plan uses the `network_item_search` bitmap index. p95 from six
or ten samples is descriptive only. These workloads exceed Mark's reported
24,222-message count but do not reproduce his message lengths, graph or aliases.

**Storage cost matters.** Eva's derived tables measured approximately291.6MB
including indexes:dependencies223.5MB (402,665 estimated rows),items40.4MB,
source mirror27.6MB. Fictional24,222 dependencies/items used205.1/81.9MB;
48,000 used535.1/169.7MB. Check provider quota before initial backfill. These
figures do not predict every customer's storage requirements.

## Failures found and resolved

- The first backfill exposed quadratic duplicated contact-history dependencies:
  a200-message regression generated83,217 dependencies. It was stopped and its
  transaction rollback verified (version0,zero mirror rows). Per-message identity
  binding was separated from contact visibility proof; the corrected real
  backfill published version1 after about251s snapshot-to-publication.
- A group-message stress probe returned an empty evidence pack. It was rejected
  as a failed workload, not counted as fast retrieval. Authored passages now
  remain searchable observations without inventing person-to-person links.
- Browser acceptance found missing-channel rendering and confirmed-proposal
  validation errors. Real name search also used the old synthetic owner. All
  received regression coverage and fixes.
- Shared source proof was transferred repeatedly; server-side deduplication and
  a composite-index join now reduce transfer while rejecting conflicting proof.
- The earlier clean-install PowerShell wrapper treated pip's update notice on
  stderr as an error. Dependency/import/resource checks confirmed installation;
  the final installer records pip's own exit code separately.

## Remaining limits and target checks

No actual new source import was observed during the real acceptance window.
The live worker maintained fresh checks without errors; import,correction,
deletion,restart and recovery transitions were exercised with isolated fixtures.
Automatic approval rejected stopping/restarting the earlier trial processes
without a specific reason, so they were retained and the new app uses5059.
The worker's autocommit lease fix passed tests but has not been installed by
restarting that retained real process; the new deployment command uses it.

Mac execution and Mark-specific semantic verification remain pending. Check
his own source binding, known identities/citations, quotas and normal imports.
Activity describes a bounded message slice, not full history, trust or delivery.
Historical identity reconstruction is unsupported. Shared affiliation does not
prove acquaintance. Unrecorded capabilities remain unknown. No private source
content, prompts, credentials or screenshots are published in these reports.

See the [upgrade guide](network-trial-upgrade.md) and
[delivery record](2026-10-02-mark-local-delivery.md) for release availability.

Reference checks:Flask's [TRUSTED_HOSTS](https://flask.palletsprojects.com/en/stable/config/#TRUSTED_HOSTS)
was added in3.1; Playwright documents the
[Edge installation command](https://playwright.dev/python/docs/browsers#installing-google-chrome--microsoft-edge).
The CI browser installation applies to disposable runners, not Eva's computer.
