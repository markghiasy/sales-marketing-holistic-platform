## 1. Fix is_automated persistence

- [x] 1.1 Add a failing test to `tests/test_store_writer.py`: an envelope
      with `is_automated=True` results in a `message` row with
      `is_automated = True` (query it back after `upsert`).
- [x] 1.2 Add `is_automated` to `store_writer.upsert()`'s `insert into
      message` column list and value tuple (reads `env.is_automated`).
- [x] 1.3 Confirm the new test passes; run `tests/test_store_writer.py`
      in full to confirm no regression.

## 2. Outlook tier 1 — remaining signals

- [x] 2.1 Add failing tests to `tests/test_outlook_sync.py`'s
      `TestToEnvelope`: List-Unsubscribe header sets `is_automated=True`;
      a known automated sender pattern (e.g. `noreply@example.com`) sets
      it True; a known automated domain sets it True; none of the above
      plus a `"focused"` classification leaves it False.
- [x] 2.2 In `adapters/outlook/sync.py`, add the header check, sender
      pattern list, and domain list (see design.md for the exact seed
      lists), combined with the existing classification check via OR, in
      `_to_envelope`.
- [x] 2.3 Confirm all new tests pass; run `tests/test_outlook_sync.py` in
      full to confirm no regression.

## 3. Tier 2 — reply signal lookup

- [x] 3.1 Write failing tests in a new `tests/test_reply_signal.py`:
      a contact with real message history returns real
      sent_count/received_count/reciprocity_ratio/last_contact_at; a
      contact with no history returns an object with all fields `None`,
      not an error.
- [x] 3.2 Create `adapters/reply_signal.py` with a `ReplySignal` dataclass
      (sent_count, received_count, reciprocity_ratio, last_contact_at —
      all `int | float | datetime | None`) and
      `reply_signal(cur, contact_key: str) -> ReplySignal`, querying
      `contact_stats`/`contact_reciprocity` (db/migrations/0002_graph_views.sql)
      by `contact_key`.
- [x] 3.3 Confirm the new tests pass.

## 4. Wrap-up

- [x] 4.1 Run the full test suite, confirm no regressions. (176 passed.)
- [x] 4.2 Docker came up mid-implementation; spot-checked real ingested
      Outlook mail. **Real finding, not a code bug:** `select count(*)
      filter (where is_automated), count(*) from message where channel =
      'outlook'` returned `0 / 4769` — every existing row still shows
      `is_automated = false`, including obvious automated senders already
      in the store (`no-reply@edm.cba.com.au`, `noreply@ventraip.com.au`,
      etc.), because those rows were ingested before this fix and
      `store_writer.upsert`'s `on conflict (channel, external_id) do
      nothing` means simply re-running the Outlook sync will NOT
      retroactively update them. The new tier-1 logic is verified correct
      in isolation (23+ unit tests), but a **backfill (an UPDATE
      recomputing is_automated for existing rows, or a full
      wipe-and-re-ingest) is a real follow-up need, out of this change's
      scope** — flagged for Eva, not built unprompted.
      Note: the sender-pattern check uses exact local-part matching
      (`local_part.lower() in _AUTOMATED_SENDER_PATTERNS`), per spec —
      not a substring match. So a backfill alone would not flag every
      "obviously automated" address; e.g.
      `mssecurity-noreply@microsoft.com` has a local part that *contains*
      `noreply` but isn't an exact match, so it would still show
      `is_automated=false` even after a backfill. This is spec-compliant
      behavior, not a bug. Separately, 192 real messages in the mailbox
      have a local-part that *contains* an automated pattern as a
      substring (not an exact match) and no List-Unsubscribe header —
      e.g. `account-security-noreply@accountprotection.microsoft.com`,
      `azure-noreply@microsoft.com`, `ato-otp-noreply@ato.gov.au`,
      `meetings-noreply@google.com`. A substring/prefix match on
      `noreply`/`no-reply` would additionally catch these ~192 messages —
      flagged as a possible cheap follow-up, not implemented here (out of
      scope for this documentation correction).
- [x] 4.3 Presented for review.

