# Noise Parser Tier 1 + Tier 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `message.is_automated` reflect reality (a real persistence
bug fix), complete build plan §9's tier 1 noise-parser signals for
Outlook, and add a tier 2 reply-signal lookup — all model-call-free, all
unblocked by Mark's still-pending model API decision.

**Architecture:** Three independent, small changes: a one-line fix to the
existing insert in `adapters/store_writer.py`; additional detection logic
inside `adapters/outlook/sync.py`'s existing `_to_envelope` function
(no new module — tier 1's remaining signals are Outlook-only, no second
caller exists); and a new small module, `adapters/reply_signal.py`, for
tier 2, which is channel-agnostic and queries existing views.

**Tech Stack:** Python, psycopg (v3), PostgreSQL, pytest.

## Global Constraints

- No database migration in this plan — `message.is_automated` and the `contact_stats`/`contact_reciprocity` views (`db/migrations/0002_graph_views.sql`) already exist.
- Tier 1's remaining signals apply to Outlook only — no changes to `adapters/whatsapp/` or `adapters/linkedin/`.
- Tests use the `db_conn` fixture from `tests/conftest.py` (local docker-compose Postgres, transaction rolled back at teardown) — never the hosted Supabase instance.
- Follow existing test fixture conventions exactly: `tests/test_store_writer.py`'s `_make_envelope()` helper pattern, `tests/test_outlook_sync.py`'s `TestToEnvelope._BASE_RAW` class-var pattern.

---

### Task 1: Fix `is_automated` persistence in `store_writer.upsert`

**Files:**
- Modify: `adapters/store_writer.py`
- Test: `tests/test_store_writer.py`

**Interfaces:**
- Consumes: `Envelope.is_automated` (already exists, `adapters/envelope.py`).
- Produces: `message.is_automated` in the store now reflects `env.is_automated` — no signature change to `upsert(conn, env, self_handle)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_store_writer.py`, inside `class TestUpsert`:

```python
    def test_persists_is_automated_true(self, db_conn: psycopg.Connection):
        env = _make_envelope(is_automated=True)
        upsert(db_conn, env, self_handle="me@example.com")

        cur = db_conn.cursor()
        cur.execute(
            "select is_automated from message where channel = %s and external_id = %s",
            (env.channel.value, env.external_id),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] is True

    def test_persists_is_automated_false(self, db_conn: psycopg.Connection):
        env = _make_envelope(is_automated=False)
        upsert(db_conn, env, self_handle="me@example.com")

        cur = db_conn.cursor()
        cur.execute(
            "select is_automated from message where channel = %s and external_id = %s",
            (env.channel.value, env.external_id),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_store_writer.py -v -k persists_is_automated`
Expected: both FAIL — `is_automated` isn't selected in the query above
because the column was never populated by `upsert`, but more precisely:
the column exists with `default false`, so
`test_persists_is_automated_false` would actually pass by accident today
(the default happens to match). `test_persists_is_automated_true` is the
one that reliably FAILS (`assert False is True`), proving the bug. Run
both anyway so the passing one is a documented baseline, not a gap.

- [ ] **Step 3: Fix the INSERT**

In `adapters/store_writer.py`, find this block (inside `upsert`):

```python
        cur.execute(
            """
            insert into message
                (thread_id, channel, external_id, direction, sent_at,
                 from_identity_id, subject, body_text, raw)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (channel, external_id) do nothing
            returning id
            """,
            (
                thread_id, env.channel.value, env.external_id, env.direction.value,
                env.sent_at, from_identity_id, env.subject, env.body_text,
                psycopg.types.json.Json(env.raw),
            ),
        )
```

Replace it with:

```python
        cur.execute(
            """
            insert into message
                (thread_id, channel, external_id, direction, sent_at,
                 from_identity_id, subject, body_text, is_automated, raw)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (channel, external_id) do nothing
            returning id
            """,
            (
                thread_id, env.channel.value, env.external_id, env.direction.value,
                env.sent_at, from_identity_id, env.subject, env.body_text,
                env.is_automated, psycopg.types.json.Json(env.raw),
            ),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_store_writer.py -v`
Expected: PASS — every test in the file, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add adapters/store_writer.py tests/test_store_writer.py
git commit -m "Persist is_automated on message insert — was silently always false"
```

---

### Task 2: Outlook tier 1 — List-Unsubscribe header

**Files:**
- Modify: `adapters/outlook/sync.py`
- Test: `tests/test_outlook_sync.py`

**Interfaces:**
- Consumes: `raw["internetMessageHeaders"]` (already fetched, used by `_resolve_sent_at`).
- Produces: `_to_envelope` sets `is_automated=True` when this header is present — no signature change.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_outlook_sync.py`, inside `class TestToEnvelope`:

```python
    def test_is_automated_true_for_list_unsubscribe_header(self):
        raw = dict(
            self._BASE_RAW,
            internetMessageHeaders=[{"name": "List-Unsubscribe", "value": "<mailto:x@y.com>"}],
        )
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_true_for_lowercase_list_unsubscribe_header_name(self):
        raw = dict(
            self._BASE_RAW,
            internetMessageHeaders=[{"name": "list-unsubscribe", "value": "<mailto:x@y.com>"}],
        )
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_outlook_sync.py -v -k list_unsubscribe`
Expected: both FAIL — `is_automated` is `False` since nothing checks for
this header yet.

- [ ] **Step 3: Add the header check**

In `adapters/outlook/sync.py`, find `_to_envelope`:

```python
def _to_envelope(raw: dict, self_handles: set[str]) -> Envelope | None:
    if raw.get("internetMessageId") is None:
        return None  # can't guarantee idempotency without it — drop, don't guess

    from_addr = raw.get("from", {}).get("emailAddress", {})
    from_handle = (from_addr.get("address") or "").lower()
    to_addrs = [r.get("emailAddress", {}) for r in raw.get("toRecipients", [])]
    to_handles = [(a.get("address") or "").lower() for a in to_addrs]

    direction = Direction.outbound if from_handle in self_handles else Direction.inbound

    return Envelope(
        channel=Channel.outlook,
        external_id=raw["internetMessageId"],
        thread_external_id=raw.get("conversationId", ""),
        direction=direction,
        sent_at=_resolve_sent_at(raw),
        from_handle=from_handle,
        to_handles=to_handles,
        from_display_name=from_addr.get("name") or None,
        to_display_names=[a.get("name") or None for a in to_addrs],
        subject=raw.get("subject"),
        body_text=_strip_html(raw.get("body", {})),
        is_group=len(to_handles) > 1,
        # §9 tier 1's own table names this exact signal: "Graph's own
        # Focused/Other classification. Sets is_automated at ingest." Not
        # the full tier-1 ruleset (List-Unsubscribe header, known
        # automated domains, bulk-sender patterns) — those still belong
        # to the real Block B noise-parser build — just this one field,
        # since Graph already computes it and hands it back for free.
        is_automated=raw.get("inferenceClassification") == "other",
        raw=raw,
    )
```

Replace the `return Envelope(...)` block with:

```python
    headers = raw.get("internetMessageHeaders") or []
    has_list_unsubscribe = any(h.get("name", "").lower() == "list-unsubscribe" for h in headers)

    return Envelope(
        channel=Channel.outlook,
        external_id=raw["internetMessageId"],
        thread_external_id=raw.get("conversationId", ""),
        direction=direction,
        sent_at=_resolve_sent_at(raw),
        from_handle=from_handle,
        to_handles=to_handles,
        from_display_name=from_addr.get("name") or None,
        to_display_names=[a.get("name") or None for a in to_addrs],
        subject=raw.get("subject"),
        body_text=_strip_html(raw.get("body", {})),
        is_group=len(to_handles) > 1,
        # §9 tier 1, combined via OR — any one signal is enough:
        # - Graph's own Focused/Other classification (free, already computed)
        # - a List-Unsubscribe header (bulk/marketing mail marks itself)
        # Sender pattern/domain checks are added in the next task.
        is_automated=(
            raw.get("inferenceClassification") == "other"
            or has_list_unsubscribe
        ),
        raw=raw,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_outlook_sync.py -v`
Expected: PASS — every test in the file, including the two new ones and
the two pre-existing `is_automated` tests (which don't set
`internetMessageHeaders` to anything containing this header, so they're
unaffected).

- [ ] **Step 5: Commit**

```bash
git add adapters/outlook/sync.py tests/test_outlook_sync.py
git commit -m "Tier 1: detect List-Unsubscribe header"
```

---

### Task 3: Outlook tier 1 — sender pattern and domain matching

**Files:**
- Modify: `adapters/outlook/sync.py`
- Test: `tests/test_outlook_sync.py`

**Interfaces:**
- Consumes: `from_handle` (already computed in `_to_envelope`).
- Produces: `_to_envelope` sets `is_automated=True` for a matching sender local-part or domain — no signature change.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_outlook_sync.py`, inside `class TestToEnvelope`:

```python
    def test_is_automated_true_for_noreply_local_part(self):
        raw = dict(self._BASE_RAW, **{"from": {"emailAddress": {"address": "noreply@example.com", "name": "Example"}}})
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_true_for_notifications_local_part(self):
        raw = dict(self._BASE_RAW, **{"from": {"emailAddress": {"address": "notifications@github.com", "name": "GitHub"}}})
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_true_for_known_automated_domain(self):
        raw = dict(self._BASE_RAW, **{"from": {"emailAddress": {"address": "updates@sendgrid.net", "name": "SendGrid"}}})
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_false_for_ordinary_sender(self):
        env = _to_envelope(self._BASE_RAW, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is False
```

Note: `test_is_automated_false_for_ordinary_sender` duplicates the
existing `test_is_automated_false_for_focused_classification` in intent
but is worth keeping explicit here as the "none of tier 1's signals fire"
baseline for this task specifically.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_outlook_sync.py -v -k "noreply_local_part or notifications_local_part or known_automated_domain"`
Expected: all three FAIL — nothing checks sender patterns or domains yet.

- [ ] **Step 3: Add the pattern and domain checks**

In `adapters/outlook/sync.py`, near the top of the file (module level,
after the existing imports), add:

```python
# §9 tier 1: sender local-part patterns that mark automated mail —
# separate list from any "generic role address" concept used elsewhere
# (identity resolution's safety checks) — this list means "this sender
# is a machine," not "this address might be shared by several humans."
_AUTOMATED_SENDER_PATTERNS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "notifications", "notification", "alerts", "alert",
    "mailer-daemon", "postmaster",
})

# §9 tier 1: known automated/ESP sending domains. A seed list, not
# verified against real mailbox data yet (Docker was down while this was
# designed) — extend with a one-line diff once real automated senders
# are seen that this list misses.
_AUTOMATED_SENDER_DOMAINS = frozenset({
    "sendgrid.net", "mailgun.org", "amazonses.com",
    "mailchimp.com", "notifications.google.com",
})


def _sender_looks_automated(from_handle: str) -> bool:
    local_part, _, domain = from_handle.partition("@")
    if local_part.lower() in _AUTOMATED_SENDER_PATTERNS:
        return True
    if domain.lower() in _AUTOMATED_SENDER_DOMAINS:
        return True
    return False
```

Then in `_to_envelope`, update the `is_automated` expression:

```python
        is_automated=(
            raw.get("inferenceClassification") == "other"
            or has_list_unsubscribe
        ),
```

becomes:

```python
        is_automated=(
            raw.get("inferenceClassification") == "other"
            or has_list_unsubscribe
            or _sender_looks_automated(from_handle)
        ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_outlook_sync.py -v`
Expected: PASS — every test in the file.

- [ ] **Step 5: Commit**

```bash
git add adapters/outlook/sync.py tests/test_outlook_sync.py
git commit -m "Tier 1: detect known automated sender patterns and domains"
```

---

### Task 4: Tier 2 — `adapters/reply_signal.py`

**Files:**
- Create: `adapters/reply_signal.py`
- Test: `tests/test_reply_signal.py`

**Interfaces:**
- Consumes: `contact_stats`/`contact_reciprocity` views (`db/migrations/0002_graph_views.sql`), already exist, no migration needed.
- Produces: `ReplySignal` dataclass (`sent_count: int | None`, `received_count: int | None`, `reciprocity_ratio: float | None`, `last_contact_at: datetime | None`) and `reply_signal(cur, contact_key: str) -> ReplySignal`. This is new infrastructure with no caller yet (Block C, the triage inbox, doesn't exist).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reply_signal.py`:

```python
# tests/test_reply_signal.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg

from adapters.reply_signal import reply_signal


def _make_identity(cur, channel: str, handle: str, is_self: bool = False) -> str:
    cur.execute(
        "insert into identity (channel, handle, is_self) values (%s, %s, %s) returning id",
        (channel, handle, is_self),
    )
    return str(cur.fetchone()[0])


def _make_thread(cur, channel: str) -> str:
    external_id = f"thread-{uuid.uuid4().hex}"
    cur.execute(
        "insert into thread (channel, external_id) values (%s, %s) returning id",
        (channel, external_id),
    )
    return str(cur.fetchone()[0])


def _make_message(
    cur, thread_id: str, channel: str, direction: str, from_identity_id: str,
    participant_ids: list[str], sent_at: datetime,
) -> str:
    external_id = f"msg-{uuid.uuid4().hex}"
    cur.execute(
        """
        insert into message (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, raw)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (thread_id, channel, external_id, direction, sent_at, from_identity_id, "hi", psycopg.types.json.Json({})),
    )
    message_id = str(cur.fetchone()[0])
    for identity_id in participant_ids:
        role = "from" if identity_id == from_identity_id else "to"
        cur.execute(
            "insert into message_participant (message_id, identity_id, role) values (%s, %s, %s)",
            (message_id, identity_id, role),
        )
    return message_id


class TestReplySignal:
    def test_contact_with_message_history(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"contact-{uuid.uuid4().hex}@example.com")
        thread_id = _make_thread(cur, "outlook")

        now = datetime.now(UTC)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now - timedelta(days=2))
        _make_message(cur, thread_id, "outlook", "outbound", self_id, [self_id, contact_id], now - timedelta(days=1))

        result = reply_signal(cur, contact_id)

        assert result.sent_count == 1
        assert result.received_count == 1
        assert result.reciprocity_ratio == 1.0
        assert result.last_contact_at is not None

    def test_contact_with_no_message_history(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = str(uuid.uuid4())  # no identity/message rows at all for this id

        result = reply_signal(cur, contact_id)

        assert result.sent_count is None
        assert result.received_count is None
        assert result.reciprocity_ratio is None
        assert result.last_contact_at is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_reply_signal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.reply_signal'`.

- [ ] **Step 3: Write the implementation**

Create `adapters/reply_signal.py`:

```python
"""Tier 2 of the noise parser (build plan §9): "have I ever replied to
this sender? how recently, how often?" — a relational signal, no model
call. Built on the contact_stats/contact_reciprocity views
(db/migrations/0002_graph_views.sql), which already compute this from
message_participant — no new schema.

No caller yet: Block C's triage inbox is the eventual consumer and
doesn't exist yet. This module is infrastructure for when it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ReplySignal:
    sent_count: int | None
    received_count: int | None
    reciprocity_ratio: float | None
    last_contact_at: datetime | None


def reply_signal(cur, contact_key: str) -> ReplySignal:
    cur.execute(
        """
        select s.sent_count, s.received_count, r.reciprocity_ratio, s.last_contact_at
        from contact_stats s
        left join contact_reciprocity r on r.contact_key = s.contact_key
        where s.contact_key = %s
        """,
        (contact_key,),
    )
    row = cur.fetchone()
    if row is None:
        return ReplySignal(None, None, None, None)
    sent_count, received_count, reciprocity_ratio, last_contact_at = row
    return ReplySignal(sent_count, received_count, reciprocity_ratio, last_contact_at)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_reply_signal.py -v`
Expected: PASS — both tests.

- [ ] **Step 5: Commit**

```bash
git add adapters/reply_signal.py tests/test_reply_signal.py
git commit -m "Tier 2: add reply_signal lookup over existing contact views"
```

---

### Task 5: Full regression + wrap-up

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS, including every test touched by Tasks 1-4 and no
regressions elsewhere (nothing else reads `is_automated` or calls
`_to_envelope`/`reply_signal` yet, so no other test should be affected).

- [ ] **Step 2: Spot-check tier 1 against real data, if available**

If the local docker-compose Postgres and a real ingested Outlook mailbox
are available:
```bash
docker exec -i $(docker compose ps -q postgres) psql -U comms -d comms -c "select count(*) filter (where is_automated), count(*) from message where channel = 'outlook'"
```
Read the actual ratio — does it look plausible for this mailbox? Note
anything surprising in the commit message or a follow-up note. If Docker
isn't up at implementation time, skip this step explicitly and say so —
don't guess at a number.

- [ ] **Step 3: Update the OpenSpec change's tasks.md**

Check off every completed item in
`openspec/changes/noise-parser-tier-1-2/tasks.md` against what this plan
actually built.

- [ ] **Step 4: Present for review, then archive**

Once Eva has reviewed the implementation, run `/opsx:archive
noise-parser-tier-1-2` (or ask Claude to archive it) to sync
`specs/noise-parser-tier-1-2/spec.md` into `openspec/specs/`.
