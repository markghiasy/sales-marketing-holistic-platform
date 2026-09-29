# Install the local Network trial alongside Ironman

This guide is for an existing working Ironman instance, including Mark's Mac.
It reuses that machine's database and API configuration. The original Inbox
and collectors continue running; the trial is a separate local app and worker.

Candidate ref: `network-trial-2026-10-02-rc1`. Fetch and verify its availability;
use it as `RELEASE_REVISION` below.

Release revision and measured validation: [delivery record](2026-10-02-mark-local-delivery.md)
and [acceptance report](2026-10-02-real-network-validation.md). Use the recorded
revision once its release gate is marked ready. Mac execution remains pending
until these checks run on the target Mac.

## 1. Prepare an isolated checkout

In the existing repository, inspect `git status --short` and preserve any local
changes. Fetch the recorded release branch/revision. Create a separate worktree
at that revision; do not replace the running application's checkout.

```sh
git fetch origin --tags
git worktree add --detach ../ironman-network-trial RELEASE_REVISION
cd ../ironman-network-trial
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -c "import adapters.network.service, scripts.network_real, scripts.network_worker; print('imports ok')"
```

Replace `RELEASE_REVISION` with the **accessible commit** in the delivery record.
Keep this complete source checkout: templates, static files and `db/network`
are runtime resources. Installing the wheel alone is insufficient.

Use an absolute path to the existing `.env` in subsequent commands. On Mac:

```sh
TRIAL_ENV='/absolute/path/to/existing/ironman/.env'
.venv/bin/python -m scripts.network_audit --env-file "$TRIAL_ENV"
```

The audit prints counts, capabilities and an opaque source binding, never
credentials or message text. Confirm these belong to this operator's source.
It needs an explicitly configured self identity; multiple self aliases are
supported without merging source people. It does not require `ai_brief_status`.

## 2. Initialize only derived state

Check the database provider's available storage quota first. In Eva's measured
7,343-message source, the derived schema used about292MB including indexes;
fictional larger workloads used more. Aliases, message length and topology
change that cost. This trial does not move the source to a local database or
promise that every existing free-tier quota is sufficient.


```sh
.venv/bin/python -m scripts.network_schema --env-file "$TRIAL_ENV" --check
```

An absent schema on first install is expected. Other failures require diagnosis
before writing. If a recognized `network` schema already exists, back it up
using the operator's normal PostgreSQL backup tooling (`pg_dump --schema=network`,
plus role grants), retaining the source binding and review history. Keep backups
private; they contain source excerpts. Do not treat a different binding or
unknown schema version as an empty installation.

For the first installation, explicitly initialize:

```sh
.venv/bin/python -m scripts.network_schema --env-file "$TRIAL_ENV" --initialize
.venv/bin/python -m scripts.network_schema --env-file "$TRIAL_ENV" --check
.venv/bin/python -m scripts.network_worker --env-file "$TRIAL_ENV" --once
```

This transaction creates the `network` schema and a restricted, non-login
`ironman_network_writer` role. The configured DB user needs schema/role creation
and role-membership privileges. Ordinary worker writes run under that role;
source reads use explicit read-only transactions. Initialization refuses a writer
that inherits source write access. If the provider disallows these privileges,
stop and report the constraint; do not grant broad source access to get past it.
Use a direct or session-mode PostgreSQL connection for the worker's advisory lock.

**Do not rerun `db/migrations/*.sql` for this trial.** Duplicate-table errors are
not proof that a multi-statement source migration is complete.

The first worker run must finish with a nonzero version, populated refresh times
and no `error_code`. It can take minutes. A failed backfill keeps the last
published graph; rerunning retries rather than publishing a partial graph.

## 3. Run locally

Check that port 5057 is free (`lsof -nP -iTCP:5057 -sTCP:LISTEN` on Mac).
Choose another free port if occupied. In two terminals, from the trial checkout:

```sh
# Terminal 1
.venv/bin/python -m scripts.network_worker --env-file "$TRIAL_ENV"
```

```sh
# Terminal 2: set TRIAL_ENV here too, since shell variables are per terminal.
.venv/bin/python -m scripts.network_real --env-file "$TRIAL_ENV" --port 5057
```

Open `http://127.0.0.1:5057/inbox` or `/network`. The app binds loopback only;
debug mode and the reloader are disabled. The first trial uses these explicit
foreground processes; closing a terminal stops its process. Keep them open during
testing. A persistent launchd service is a later operational choice, not a hidden
installation step.

Windows equivalents use `.venv\Scripts\python.exe`, PowerShell `$trialEnv`, and
`Get-NetTCPConnection -State Listen`. If an agent starts background processes on
Windows, it must use hidden windows and retain the exact process IDs for stopping.

## 4. Verify actual behavior

```sh
.venv/bin/python -m scripts.check_network_real --base-url http://127.0.0.1:5057
```

Require `ready: true`, real source mode, a PostgreSQL graph, current refresh times
and inspectable citations. This smoke check makes no model calls and changes no
source data. It samples a bounded view; it does not prove every contact is correct.

Then check these in the UI:

1. Open a known contact, its embedded graph and original evidence. Check the
   identity and source attribution. Load additional contact pages when needed.
2. Open the full graph. Use the four relationship scopes. Shared employers are
   context, not evidence of acquaintance or willingness to introduce.
3. Search a name and a goal. With an existing Anthropic API key, explicitly ask
   one strategy question and inspect its evidence, candidate subgraph and unknowns.
   Model unavailability should leave graph and ordinary search usable.
4. Select a small number of messages in a strategic profile and extract a draft.
   Review quotations and entity bindings before confirming. Reject incorrect
   batches; confirmed projects and assertions should appear after refresh.
5. Leave **Live updates** enabled. After the existing collector ingests a real
   message, check source refresh and the affected view. Do not fabricate production
   messages for this check. Restart the trial and verify review history persists.

The default worker polls new messages every 60 seconds, checks metadata every
300 seconds and fully reconciles every 900 seconds. These are scheduling
intervals, not latency guarantees; a long pass, offline source or sleeping Mac
delays refresh. The UI displays the last successful state and stale health.

Known boundaries: candidate/evidence budgets can omit results; activity metrics
describe the loaded slice; missing records mean unknown; the historical view
filters source time but does not reconstruct old identity assignments. Whole-history
LLM extraction is off. Model/extraction requests share a bounded process-session
budget. Requests can use two model calls; inspect provider usage before increasing
limits. Existing summary-generation jobs are unchanged by this trial.

## 5. Stop and recover

Press Ctrl+C in the two trial terminals. The original Ironman remains available.
Keep the `network` schema and review audit for restart; stopping is the normal
rollback. Do not delete source tables or recreate the source database. If a future
release changes the derived schema version, require a documented migration and
verified backup restore first. Report an error code, app revision, aggregate
counts and timings; never paste `.env`, messages or private names into issue logs.
