# Why the baseline CI passed, and how database tests are isolated

Investigated 2026-09-28 against `main` commit
`7c739a2cd46fadacc0be86c7e711c31824b30bec`.

## What the actual CI run proves

[GitHub Actions run 35423826103](https://github.com/markghiasy/sales-marketing-holistic-platform/actions/runs/35423826103)
ran on 2026-09-19 at the exact baseline commit. Its `test` log records:

```text
2026-09-19T05:24:06.6201246Z collecting ... collected 305 items
2026-09-19T05:24:07.8340901Z TestInboxRoutes::test_conversations_json_lists_seeded_contact PASSED
2026-09-19T05:24:07.8546595Z TestInboxRoutes::test_conversation_detail_json_returns_messages PASSED
2026-09-19T05:24:07.8645977Z TestInboxRoutes::test_conversation_detail_json_404s_for_unknown_person PASSED
2026-09-19T05:24:07.8908963Z TestInboxRoutes::test_mark_read_updates_thread PASSED
2026-09-19T05:24:08.7878802Z 305 passed in 2.71s
```

The old workflow started a fresh PostgreSQL 16 service at port 5432 with
database/user/password `comms`. That matched the hardcoded test DSNs.
It applied the SQL migrations before running `pytest -v`. These tests were
not skipped and did not merely report success without a database.

The baseline's `_seed_inbox_conversation` already calls `db_conn.commit()`
before making a route request. That makes seeded rows visible to the
application's independent connection under normal PostgreSQL transaction
isolation. This commit was present before the baseline, including in
`c21b9bb`; it was not introduced by this fix.

Therefore the specific claim that the checked-in Inbox helper leaves seeds
uncommitted does not describe this exact baseline. We did not inspect Mark's
machine or its failure traceback and cannot establish its precise local
cause. A different checkout/helper, local database state, or connection
configuration would need to be compared. These are possibilities, not
verified explanations of that failure.

## Confirmed weaknesses in the baseline

- `tests/conftest.py` ignored any selected database URL and connected to
  hardcoded `localhost:5432/comms`. The route tests and brief integration
  tests duplicated that choice. Changing `DATABASE_URL` could not relocate
  the suite to a disposable database on another port.
- The generic fixture rolled back, but several integration tests explicitly
  committed to let other connections see data. Their isolation depended on
  hand-maintained cleanup lists; rollback cannot remove committed rows.
- The app caches `_db_conn` globally. Changing the environment does not
  replace an already-open connection. The old tests did not reset this
  connection at their isolation boundary.
- The store-writer module silently skipped when its hardcoded local database
  was unavailable. The verified baseline run did not take that skip branch,
  but an unavailable database could hide those tests in another run.
- The migration command lacked `ON_ERROR_STOP`. A SQL error did not reliably
  stop `psql` or prevent later migrations/tests from running.

## Changes

Database fixtures now require **`TEST_DATABASE_URL` explicitly**, with no
fallback to application `DATABASE_URL` or dotenv loading. The target must be
loopback and its database name must start with `test_` or end with `_test` or
`_tests`. The connection also pins `hostaddr` so an unrelated `PGHOSTADDR`
cannot redirect it. Do not point this variable at a database with useful data.

Each database test creates a UUID-named schema, applies all checked-in
migrations there, and sets application `DATABASE_URL` to the same schema's
connection string. The search path includes only that schema (plus implicit
PostgreSQL system catalogs), so a missing migrated table cannot fall back to
a table in `public`. The database-level `pgcrypto` extension is installed in
`public` once if needed; test data stays in the generated schema.

Ordinary `db_conn` tests still roll back on teardown. Integration tests can
commit normally and open genuine independent connections. Teardown drops
only the generated schema, removing committed and uncommitted test data
even if the test fails. Onboarding route tests close/reset the app's cached
connection before and after each test; production app connection code is
unchanged by this test-infrastructure change.

The store-writer availability skip was removed: missing configuration or an
unreachable database fails database tests. Non-database unit tests remain
runnable without Postgres.

CI now uses the explicit `comms_test` database, applies migrations with
`set -euo pipefail` and `psql -X -v ON_ERROR_STOP=1`, runs the complete suite,
and emits JUnit XML. A separate step rejects skipped tests and verifies the
Inbox, store-writer and isolation test groups are present and passing. The
XML is uploaded even when a later step fails, making executed-test evidence
reviewable beyond the green status icon.

## Validation and local reproduction

On a disposable PostgreSQL 16 instance at a non-default loopback port:

- New configuration regressions failed before the implementation, then
  passed: missing explicit URL, refusal of a remote host or non-test database,
  and honoring the selected port.
- A committed seed was read from a different PostgreSQL backend connection.
- A deliberate exception after committed writes removed the test schema.
- All four Inbox route tests passed using the schema-scoped database URL.
- The owned test group passed: **44 passed**, zero skips, comprising
  `test_database_isolation.py`, `test_onboarding_app.py`, and `test_store_writer.py`.
- Ruff passed for those changed Python files.

Use a fresh local database and an explicit URL, for example:

```bash
export TEST_DATABASE_URL=postgresql://comms:comms@127.0.0.1:55432/comms_test
export PYTHON_DOTENV_DISABLED=1
python -m pytest -v --junitxml=test-results.xml
```

The fixtures apply migrations themselves, so that command does not require
pre-populating a shared development database. The database role needs schema
creation and migration permissions on this disposable database. The CI
workflow separately exercises migration application through `psql` as well.

This change verifies test execution and isolation. It does not establish
identity-resolution precision; that requires the separate blind quality
measurement described in the quality gate.
