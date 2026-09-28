# Resolution quality remediation — 2026-09-28

Baseline: `7c739a2cd46fadacc0be86c7e711c31824b30bec`.
This change addresses candidate quality, merge attribution, brief reliability,
and reproducible database tests. It does not claim fresh real-data quality
acceptance or a production deployment.

## Behavior

- Retire `linkedin_same_channel_dedupe`: matching LinkedIn names alone no longer
  creates a review candidate. Migration 0012 withdraws existing pending rows as
  `retired`, preserving the original evidence and all confirmed/rejected history.
  It does not undo previous merges. Undoing an old merge later keeps that retired
  rule's candidate out of the review queue. A replacement needs independent evidence and
  fresh evaluation before release.
- Every new merge records its originating `method` and `decision_kind`
  (`automatic`, `review`, or `manual`). Reviewed candidates retain their actual
  rule name; manual contact links use `manual_link`. Historical records receive
  `unknown_legacy`, without inferring a rule. There are no database defaults that
  could silently omit future attribution. Existing identity undo behavior remains.
- Brief generation uses strict tool output and counts the exact prompt and tool
  schema before generation. The 160,000-token input budget reserves headroom.
  Oversized histories first lose older messages; a remaining oversized message
  can be shortened. Every change is recounted, with at most ten count requests.
  Irreducible input is explicitly skipped. These conservative bounds favor recent
  context and are not a replacement for future retrieval work.
- A separate latest-attempt status records counts, omissions, and fixed failure
  codes. A failed attempt preserves the last successful brief. The inbox shows
  partial-history and failure notices, including when it displays a cached brief.
  The newest successful cache and latest status follow a merged contact. If the database cannot record the
  outcome, sync surfaces a sanitized error; already committed messages remain.
- Tests require an explicit disposable database and isolate every test in a
  migrated schema. CI fails on migration errors and verifies database tests ran.

The verified baseline CI really executed and passed all 305 tests, including
the four Inbox tests. Its seed helper already committed. The hardcoded DSN and
isolation weaknesses were confirmed and repaired; Mark's exact local failure
still needs his traceback/checkout details to identify. See the
[CI evidence and diagnosis](ci-diagnosis.md).

## Upgrade an existing installation

Use the existing backup/change procedure and stop sync workers and the app during
the schema/code change: old merge writers do not supply the newly required fields,
and the new inbox query requires the new status table.

Install the matching package dependencies (`pip install -e .`). The minimum
Anthropic SDK is now 0.125, the version used by the strict-tool/token-count
serialization contract test; retaining an older environment can break preflight.

For an installation already migrated through 0009, apply **only** these new files
in order, then start the matching application revision:

1. `db/migrations/0010_merge_provenance.sql`
2. `db/migrations/0011_ai_brief_status.sql`
3. `db/migrations/0012_retire_linkedin_name_dedupe.sql`

For example, with the deployment database selected explicitly:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 --single-transaction \
  -f db/migrations/0010_merge_provenance.sql \
  -f db/migrations/0011_ai_brief_status.sql \
  -f db/migrations/0012_retire_linkedin_name_dedupe.sql
```

Migration 0010 is intentionally not repeatable; use the deployment's migration
record to avoid reapplying it. Fresh installations apply all migrations in order.
Do not rerun the entire historical migration directory on an existing database.
Do not roll back only application code while retaining the new mandatory merge
columns; coordinate schema and code recovery using the deployment backup.

## Acceptance and remaining owner verification

Local validation on Python 3.12, PostgreSQL 16, and Anthropic SDK 0.125:
**360 tests passed, zero skips**. Ruff, Python compilation, and whitespace checks
passed. The SDK test uses mocked HTTP; a live provider smoke test and fresh
real-data quality measurement are separate from this result. GitHub CI has not
yet run for this revision.

Software regression tests cover all three merge shapes, all production merge
entry paths, legacy attribution backfill, undo, selective candidate retirement,
counted/strict requests, failure persistence and retry recovery, and independent
database connections. Provider behavior is tested with the real SDK and mocked
HTTP responses; no customer messages were sent to a live model for these tests.

Fresh blind measurement remains **measurement_pending**. Retiring a poor rule
does not turn an old filtered sample into a fresh holdout or satisfy the unchanged
100-scored-pair review minimum. The [release policy](resolution-release-policy.md)
and aggregate-only checker preserve the queue-level Wilson gate and report unknown
rates. The new automatic-merge threshold is an explicitly proposed conservative
policy, not a threshold already accepted by Mark. No private grading tool or raw
customer pairs are included in this repository.

After installation, the data owner should verify the retired queue entries, new
merge provenance, and visible brief status, then preregister and grade a fresh
holdout. Code/test completion and measured resolution quality must be reported
separately.
