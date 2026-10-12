# Network latency diagnosis for the Friday demo

The first change reduces the database round trips used to validate live source evidence. PostgreSQL remains the source and derived store. The available trace supports reducing serial database work and repeated materialization before considering a graph database migration.

This is a verified component improvement, not a new end-to-end live latency result. The previously reported 76.995 second strategy request and roughly 5–6 second graph/name requests have not been rerun with this patch. No provider requests or writes to the real database were made for this change.

## Recorded baseline

The retained local timing artifact `.tmp/eva-agent-profiled.json` records an earlier 98.381 second strategy request. It contains these stage measurements:

| Stage | Calls | Total seconds |
| --- | ---: | ---: |
| Model request | 2 | 26.772 |
| Source validation | 3 | 11.986 |
| Derived validation | 3 | 6.093 |
| Capture | 4 | 15.267 |
| Indexed hits | 3 | 5.954 |
| Pack | 1 | 28.550 |

The trace also records materialization spans that contain capture time; those must not be added again. Stage totals are not a complete accounting of wall time. The pack measurement predates the separately completed lexical cache fix, so it is not a measurement of current packing performance.

## Implemented change and controlled comparison

`SourceRepository.validate` still starts a new read-only, repeatable-read transaction on every call. Schema and database identity are now read together with the column capabilities in one query. Independent reads of the selected dependency kinds are submitted through a psycopg pipeline. Message participants are then fetched within that same transaction, using the existing payload and fingerprint conversion.

The regression test executes actual PostgreSQL queries against a disposable loopback database. It validates the same seeded pattern of person, identity, thread, message and absent contact-hide dependencies. A wrapper adds 20 milliseconds at each sequential read exchange or pipeline synchronization, excluding connection setup and transaction completion. This makes the serial round-trip penalty reproducible without relying on internet variability.

| Validation implementation | Read exchanges | Observed component time |
| --- | ---: | ---: |
| Before | 9 | 0.253 seconds |
| After | 3 | 0.109 seconds |

These are individual controlled observations, not production percentiles. The deterministic regression assertion is the maximum of three read exchanges. The six avoided exchanges correspond to 120 milliseconds of deliberately injected delay. A higher remote RTT would increase that benefit, but the production gain requires measurement. Actual source reads still execute on the database; the pipeline reduces waiting between them rather than parallelizing server execution.

Reproduce using the repository Python environment and an explicitly configured disposable loopback `TEST_DATABASE_URL`:

```powershell
python -m pytest tests/test_network_source.py -k batches_remote -q -s -p no:cacheprovider
```

## Safety and verification

All three agent validation boundaries remain in place. No source validity, identity, schema, or binding result is cached between requests. Unknown kinds are rejected; absent optional tables retain their existing absence semantics. Field selection continues to exclude quarantined `message.raw`.

The source tests cover contact hiding, identity edits, participant edits, message deletion, binding mismatch, missing required schema, absent optional tables, and read-only enforcement. A concurrent participant edit test proves that participant and message reads share the same transaction snapshot, while the next validation observes and rejects the change. The real-agent integration tests exercise source changes around model calls with a fake provider.

## Next architecture decision

The immediate recommendation is to keep PostgreSQL and measure the patched application in its intended demo environment. This patch does not directly optimize graph rendering or name search, and those requests need their own before-and-after timings.

1. Record request wall time and separate metadata, indexed lookup, capture, packing, validation and model spans. Record connection acquisition and transaction overhead as well as query time; retain timings and counts without source text or credentials.
2. Measure warm and cold graph/name requests repeatedly without model calls. Inspect the plans for the slow indexed lookup and capture queries before changing indexes or data layout.
3. Reduce the remaining serial reads in derived validation and capture where dependencies permit. Reusing materialization requires explicit version and dependency rules; skipping fresh source checks would undermine correctness.
4. Compare the same request with the application located near PostgreSQL. The earlier hosted round-trip estimate of roughly 250 milliseconds makes locality a plausible contributor, not yet a measured deployment comparison.
5. Run a bounded strategy request only after the database and packing measurements stabilize. Separate model time from application time when deciding whether model choice or fewer model passes are needed.

A graph database evaluation becomes relevant if measured traversal workloads or graph query plans become the dominant unresolved bottleneck. The existing trace does not establish that condition, and changing storage would not by itself remove model latency, source validation, or repeated application/database exchanges.
