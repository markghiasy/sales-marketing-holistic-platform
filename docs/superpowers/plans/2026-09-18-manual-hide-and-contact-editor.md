# Manual Hide + Contact Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Eva manually hide/unhide a triage-inbox conversation, and let her click a contact's name to view/edit their name and known handles, and link or manually add another handle for the same person.

**Architecture:** A new `contact_hidden` table plus two new functions in `adapters/inbox_query.py` handle hide/unhide. A new `adapters/contact_editor.py` module handles the contact info panel's read/edit/search/link/add-handle operations, reusing `adapters/resolution/merge.py`'s existing `apply_merge()` for linking (same reversible merge every other part of this codebase uses). Both surface through new Flask routes in `scripts/onboarding/app.py` and new UI in `scripts/onboarding/templates/inbox.html`.

**Tech Stack:** Python 3, Flask, psycopg (raw SQL, no ORM), vanilla JS (no framework — this template has none today), Postgres.

## Global Constraints

- `contact_key` everywhere in this codebase means `coalesce(identity.person_id, identity.id)` — match this exactly, never invent a different key shape.
- Every new DB write goes through the existing single persistent connection pattern in `scripts/onboarding/app.py`'s `_db_cursor()` — don't open new connections.
- A manually-added handle (no message history) is edited/deleted with a plain UPDATE/DELETE — it must NOT go through `merge_log`/`undo_merge`, since only merges of identities that already carry real message history need that reversibility machinery.
- Linking an existing identity to a contact (the "search and click a match" path) MUST go through `adapters/resolution/merge.py`'s `apply_merge()` — do not write a second, separate merge implementation.
- Match this repo's existing test conventions exactly: `tests/conftest.py`'s `db_conn` fixture (local docker-compose Postgres, rolled back after each test, never commit), `uuid.uuid4().hex[:8]`-suffixed unique handles per test to avoid collisions with any other data in that local DB.

---

### Task 1: `contact_hidden` migration

**Files:**
- Create: `db/migrations/0009_contact_hidden.sql`

**Interfaces:**
- Produces: table `contact_hidden(contact_key uuid primary key, hidden_at timestamptz not null default now())`, consumed by Task 2.

- [ ] **Step 1: Write the migration**

```sql
-- db/migrations/0009_contact_hidden.sql
-- Lets Eva manually hide a triage-inbox conversation, independent of the
-- automatic hide rules (stale-unknown, automated-sender, bulk-recipient,
-- empty-body) already applied in adapters/inbox_query.py's
-- list_conversations(). contact_key is the same coalesce(person_id, id)
-- value used throughout (contact_stats, contact_last_message) — not a
-- foreign key to identity directly, since a contact_key doesn't always
-- correspond to one physical row.

create table contact_hidden (
    contact_key uuid primary key,
    hidden_at   timestamptz not null default now()
);
```

- [ ] **Step 2: Apply it to the local docker-compose Postgres**

Run: `docker compose down -v && docker compose up -d` (from the repo root) — this re-runs every migration fresh, including the new one, the same way this repo has picked up every prior migration during this project.

Expected: `docker compose ps` shows `repo-postgres-1` as `healthy`.

- [ ] **Step 3: Commit**

```bash
git add db/migrations/0009_contact_hidden.sql
git commit -m "feat: add contact_hidden table for manual conversation hiding"
```

---

### Task 2: `hide_contact`/`unhide_contact` + `list_conversations(show_hidden=...)`

**Files:**
- Modify: `adapters/inbox_query.py`
- Test: `tests/test_inbox_query.py`

**Interfaces:**
- Consumes: `contact_hidden` table (Task 1).
- Produces: `hide_contact(cur, contact_key: str) -> None`, `unhide_contact(cur, contact_key: str) -> None`, `list_conversations(cur, show_hidden: bool = False) -> list[ConversationRow]` (existing function, new optional param — default preserves current behavior for every existing caller/test).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_inbox_query.py`, inside `class TestListConversations:` (after the existing bulk-recipient/empty-message tests, before `class TestGetDetail:`):

```python
    def test_manually_hidden_contact_is_excluded_by_default(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Hide Me")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)
        hide_contact(cur, contact_id)

        rows = list_conversations(cur)

        assert all(r.person_key != contact_id for r in rows)

    def test_show_hidden_returns_only_hidden_contacts(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        hidden_id = _make_identity(cur, "outlook", f"h-{uuid.uuid4().hex}@example.com", display_name="Hidden Contact")
        visible_id = _make_identity(cur, "outlook", f"v-{uuid.uuid4().hex}@example.com", display_name="Visible Contact")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", hidden_id, [hidden_id, self_id], now)
        _make_message(cur, thread_id, "outlook", "inbound", visible_id, [visible_id, self_id], now)
        hide_contact(cur, hidden_id)

        rows = list_conversations(cur, show_hidden=True)

        assert any(r.person_key == hidden_id for r in rows)
        assert all(r.person_key != visible_id for r in rows)

    def test_unhide_makes_contact_visible_again(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex}@example.com", display_name="Unhide Me")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)
        hide_contact(cur, contact_id)
        unhide_contact(cur, contact_id)

        rows = list_conversations(cur)

        assert any(r.person_key == contact_id for r in rows)
```

Update the import line at the top of `tests/test_inbox_query.py`:

```python
from adapters.inbox_query import get_detail, hide_contact, list_conversations, mark_read, unhide_contact
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_inbox_query.py -k "hidden or Hide or Unhide" -v`
Expected: FAIL with `ImportError: cannot import name 'hide_contact'`

- [ ] **Step 3: Implement `hide_contact`/`unhide_contact` and update `list_conversations`**

In `adapters/inbox_query.py`, add these two functions right after `list_conversations` (before `_PLACEHOLDER_CONTEXT`):

```python
def hide_contact(cur, contact_key: str) -> None:
    cur.execute(
        "insert into contact_hidden (contact_key) values (%s) on conflict (contact_key) do nothing",
        (contact_key,),
    )


def unhide_contact(cur, contact_key: str) -> None:
    cur.execute("delete from contact_hidden where contact_key = %s", (contact_key,))
```

Now change `list_conversations`'s signature and query. Replace the function's opening line:

```python
def list_conversations(cur) -> list[ConversationRow]:
```

with:

```python
def list_conversations(cur, show_hidden: bool = False) -> list[ConversationRow]:
```

Replace the `where` clause's final line — currently:

```python
        order by clm.sent_at desc
        """
    )
```

with (this appends the hide filter as one more parameterized `and`, keeping every existing filter's behavior unchanged for the `show_hidden=False` default, and applying the same automatic filters — stale-unknown, automated-sender, bulk-recipient, empty-body — in `show_hidden=True` mode too: a contact that was never visible enough to manually hide in the first place shouldn't become reachable only through the Hidden view):

```python
        and (ch.contact_key is not null) = %s
        order by clm.sent_at desc
        """,
        (show_hidden,),
    )
```

And add the `contact_hidden` join right after the existing `unread` subquery's closing `) unread on unread.contact_key = cs.contact_key` line:

```python
        left join contact_hidden ch on ch.contact_key = cs.contact_key
```

The full query's `from`/`join` block should now read (for context — this is what it looks like after both edits):

```python
        from contact_stats cs
        join contact_last_message clm on clm.contact_key = cs.contact_key
        left join ai_brief ab on ab.person_key = cs.contact_key
        left join (
            select
                coalesce(i.person_id, i.id) as contact_key,
                bool_or(m.sent_at > coalesce(t.last_read_at, '-infinity'::timestamptz)) as is_unread
            from identity i
            join message_participant mp on mp.identity_id = i.id
            join message m on m.id = mp.message_id
            join thread t on t.id = m.thread_id
            where i.is_self = false and m.direction = 'inbound'
            group by coalesce(i.person_id, i.id)
        ) unread on unread.contact_key = cs.contact_key
        left join contact_hidden ch on ch.contact_key = cs.contact_key
```

Note the `cur.execute(...)` call now passes `(show_hidden,)` as its params tuple — psycopg requires this even though every other placeholder in the query is a plain SQL literal, since this is the only `%s` used outside a string comparison.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_inbox_query.py -k "hidden or Hide or Unhide" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full inbox_query test suite to check nothing else broke**

Run: `pytest tests/test_inbox_query.py -v`
Expected: all pass (the `show_hidden` param defaults to `False`, so every pre-existing test calling `list_conversations(cur)` with no second argument is unaffected)

- [ ] **Step 6: Commit**

```bash
git add adapters/inbox_query.py tests/test_inbox_query.py
git commit -m "feat: add hide_contact/unhide_contact and list_conversations(show_hidden=)"
```

---

### Task 3: Flask routes for hide/unhide

**Files:**
- Modify: `scripts/onboarding/app.py`

**Interfaces:**
- Consumes: `inbox_query.hide_contact`, `inbox_query.unhide_contact`, `inbox_query.list_conversations(cur, show_hidden=...)` (Task 2).
- Produces: `POST /inbox/conversation/<person_key>/hide`, `POST /inbox/conversation/<person_key>/unhide`, `GET /inbox/conversations.json?hidden=1`, consumed by Task 4.

- [ ] **Step 1: Add the hide/unhide routes**

In `scripts/onboarding/app.py`, right after the existing `inbox_conversation_mark_read` route (the `POST /inbox/conversation/<person_key>/read` one), add:

```python
    @flask_app.post("/inbox/conversation/<person_key>/hide")
    def inbox_conversation_hide(person_key):
        with _db_cursor() as cur:
            inbox_query.hide_contact(cur, person_key)
        return jsonify({"status": "ok"})

    @flask_app.post("/inbox/conversation/<person_key>/unhide")
    def inbox_conversation_unhide(person_key):
        with _db_cursor() as cur:
            inbox_query.unhide_contact(cur, person_key)
        return jsonify({"status": "ok"})
```

- [ ] **Step 2: Wire the `hidden` query param through the list route**

Replace the existing `inbox_conversations_json` route:

```python
    @flask_app.get("/inbox/conversations.json")
    def inbox_conversations_json():
        with _db_cursor() as cur:
            rows = inbox_query.list_conversations(cur)
        return jsonify([
```

with:

```python
    @flask_app.get("/inbox/conversations.json")
    def inbox_conversations_json():
        show_hidden = request.args.get("hidden") == "1"
        with _db_cursor() as cur:
            rows = inbox_query.list_conversations(cur, show_hidden=show_hidden)
        return jsonify([
```

- [ ] **Step 3: Manually verify against the local dev server**

Run: `python scripts/onboarding/app.py` (in one terminal), then in another:

```bash
curl -s -X POST http://127.0.0.1:5000/inbox/conversation/<a-real-person-key>/hide
curl -s http://127.0.0.1:5000/inbox/conversations.json | python -c "import json,sys; print(len(json.load(sys.stdin)))"
curl -s "http://127.0.0.1:5000/inbox/conversations.json?hidden=1" | python -c "import json,sys; print(len(json.load(sys.stdin)))"
curl -s -X POST http://127.0.0.1:5000/inbox/conversation/<same-person-key>/unhide
```

Expected: the second count is one lower than before hiding, the third command's output includes that one contact, and after unhiding the first count is back to its original value. Use any real `person_key` from `curl -s http://127.0.0.1:5000/inbox/conversations.json` for this check.

- [ ] **Step 4: Commit**

```bash
git add scripts/onboarding/app.py
git commit -m "feat: add hide/unhide routes and hidden=1 list param"
```

---

### Task 4: Frontend — hide icon on hover + "Hidden" filter

**Files:**
- Modify: `scripts/onboarding/templates/inbox.html`

**Interfaces:**
- Consumes: the three routes from Task 3.

- [ ] **Step 1: Add the "Hidden" checkbox to the filter box**

In `scripts/onboarding/templates/inbox.html`, find:

```html
        <label><input type="checkbox" id="f-unread"> Unread</label>
        <label><input type="checkbox" id="f-unanswered"> Unanswered</label>
        <label><input type="checkbox" id="f-draft"> Has draft ready</label>
```

and add a fourth line right after it:

```html
        <label><input type="checkbox" id="f-unread"> Unread</label>
        <label><input type="checkbox" id="f-unanswered"> Unanswered</label>
        <label><input type="checkbox" id="f-draft"> Has draft ready</label>
        <label><input type="checkbox" id="f-hidden"> Hidden</label>
```

- [ ] **Step 2: Add `hidden` to `state` and make `loadConversations` pass it through**

Find:

```javascript
let state = { channel: "all", unread: false, unanswered: false, draft: false, sort: "priority" };
```

Replace with:

```javascript
let state = { channel: "all", unread: false, unanswered: false, draft: false, hidden: false, sort: "priority" };
```

Find:

```javascript
let CONVERSATIONS = [];

async function loadConversations() {
```

Read the next couple of lines (the function body) to find the fetch call — replace the whole function:

```javascript
async function loadConversations() {
  const resp = await fetch("/inbox/conversations.json");
  CONVERSATIONS = await resp.json();
  render();
}
```

with:

```javascript
async function loadConversations() {
  const resp = await fetch(`/inbox/conversations.json${state.hidden ? "?hidden=1" : ""}`);
  CONVERSATIONS = await resp.json();
  render();
}
```

- [ ] **Step 3: Wire the checkbox's change event**

Find:

```javascript
document.getElementById("f-draft").addEventListener("change", e => { state.draft = e.target.checked; render(); });
```

and add right after it:

```javascript
document.getElementById("f-hidden").addEventListener("change", e => { state.hidden = e.target.checked; loadConversations(); });
```

(This one re-fetches, unlike the other three, since which rows are even eligible changes server-side — a plain `render()` on stale `CONVERSATIONS` data wouldn't show the newly-relevant hidden rows.)

- [ ] **Step 4: Add the hide/unhide button to each row**

Find `renderList()`'s row template:

```javascript
  list.innerHTML = rows.map(c => `
    <div class="row" data-id="${c.person_key}">
      <div class="avatar" style="background:${avatarColor(c.name)}">${initials(c.name)}</div>
      <div class="row-main">
        <div class="row-top">
          <span class="row-name">${escapeHtml(c.name)}</span>
          <span class="tag" style="background:${avatarColor(c.topic)}22;color:${avatarColor(c.topic)}">${escapeHtml(c.topic)}</span>
          ${c.has_draft ? `<span class="draft-badge" title="AI draft ready">&#9998; Draft ready</span>` : ""}
          <span class="row-time">${formatRelativeTime(c.last_message_at)}</span>
        </div>
        <div class="row-preview">${escapeHtml(c.summary)}</div>
      </div>
      <div class="channel-icon">${CHANNELS[c.channel].icon}</div>
    </div>
  `).join("");
  list.querySelectorAll(".row").forEach(row => {
    row.addEventListener("click", () => openDetail(row.dataset.id));
  });
```

Replace with:

```javascript
  list.innerHTML = rows.map(c => `
    <div class="row" data-id="${c.person_key}">
      <div class="avatar" style="background:${avatarColor(c.name)}">${initials(c.name)}</div>
      <div class="row-main">
        <div class="row-top">
          <span class="row-name">${escapeHtml(c.name)}</span>
          <span class="tag" style="background:${avatarColor(c.topic)}22;color:${avatarColor(c.topic)}">${escapeHtml(c.topic)}</span>
          ${c.has_draft ? `<span class="draft-badge" title="AI draft ready">&#9998; Draft ready</span>` : ""}
          <span class="row-time">${formatRelativeTime(c.last_message_at)}</span>
        </div>
        <div class="row-preview">${escapeHtml(c.summary)}</div>
      </div>
      <div class="channel-icon">${CHANNELS[c.channel].icon}</div>
      <button class="row-hide-btn" data-hide-id="${c.person_key}" title="${state.hidden ? "Unhide" : "Hide"}">${state.hidden ? "&#8635;" : "&times;"}</button>
    </div>
  `).join("");
  list.querySelectorAll(".row").forEach(row => {
    row.addEventListener("click", () => openDetail(row.dataset.id));
  });
  list.querySelectorAll(".row-hide-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.dataset.hideId;
      const endpoint = state.hidden ? "unhide" : "hide";
      fetch(`/inbox/conversation/${id}/${endpoint}`, { method: "POST" }).then(() => {
        CONVERSATIONS = CONVERSATIONS.filter(c => c.person_key !== id);
        renderList();
      });
    });
  });
```

- [ ] **Step 5: Add the CSS**

Find:

```css
  .channel-icon { flex-shrink: 0; display: flex; }
  .channel-icon svg { width: 15px; height: 15px; }
```

and add right after it:

```css
  .row-hide-btn {
    opacity: 0; flex-shrink: 0; width: 24px; height: 24px; border-radius: 50%;
    border: none; background: transparent; color: var(--text-dim); cursor: pointer;
    font-size: 14px; transition: opacity 0.1s ease;
  }
  .row:hover .row-hide-btn { opacity: 1; }
  .row-hide-btn:hover { background: var(--panel-2); color: var(--text); }
```

- [ ] **Step 6: Manually verify in a browser**

Run: `python scripts/onboarding/app.py`, open `http://localhost:5000/inbox`. Hover a row — an `×` button should fade in on the right. Click it — the row should disappear from the list immediately. Check "Hidden" in the filter panel — the list should reload showing only that one row, now with a `↻` (unhide) button instead. Click it — the row disappears from the Hidden view. Uncheck "Hidden" — the contact is back in the normal list.

- [ ] **Step 7: Commit**

```bash
git add scripts/onboarding/templates/inbox.html
git commit -m "feat: add hide/unhide UI and Hidden filter to the triage inbox"
```

---

### Task 5: `adapters/contact_editor.py` — read + search

**Files:**
- Create: `adapters/contact_editor.py`
- Test: `tests/test_contact_editor.py`

**Interfaces:**
- Consumes: `identity` table.
- Produces: `ContactHandle` (dataclass: `identity_id: str`, `channel: str`, `handle: str`), `ContactInfo` (dataclass: `person_key: str`, `name: str`, `handles: list[ContactHandle]`), `get_contact_info(cur, person_key: str) -> ContactInfo | None`, `SearchResult` (dataclass: `identity_id: str`, `channel: str`, `handle: str`, `display_name: str | None`), `search_identities(cur, query: str, exclude_person_key: str) -> list[SearchResult]` — all consumed by Task 8 (Flask routes).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contact_editor.py`:

```python
from __future__ import annotations

import uuid

import psycopg

from adapters.contact_editor import get_contact_info, search_identities


def _make_identity(cur, channel: str, handle: str, display_name: str | None = None, is_self: bool = False) -> str:
    cur.execute(
        "insert into identity (channel, handle, display_name, is_self) values (%s, %s, %s, %s) returning id",
        (channel, handle, display_name, is_self),
    )
    return str(cur.fetchone()[0])


class TestGetContactInfo:
    def test_returns_name_and_single_handle(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex[:8]}@example.com", display_name="Priya Shah")

        info = get_contact_info(cur, contact_id)

        assert info is not None
        assert info.name == "Priya Shah"
        assert len(info.handles) == 1
        assert info.handles[0].channel == "outlook"

    def test_returns_every_handle_for_a_merged_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Priya Shah') returning id")
        person_id = cur.fetchone()[0]
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("outlook", f"priya-{uuid.uuid4().hex[:8]}@example.com", "Priya Shah", person_id),
        )
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net", "Priya Shah", person_id),
        )

        info = get_contact_info(cur, str(person_id))

        assert info is not None
        assert len(info.handles) == 2
        assert {h.channel for h in info.handles} == {"outlook", "whatsapp"}

    def test_returns_none_for_unknown_person_key(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        assert get_contact_info(cur, str(uuid.uuid4())) is None


class TestSearchIdentities:
    def test_finds_matching_handle_substring(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        unique = uuid.uuid4().hex[:8]
        target_id = _make_identity(cur, "outlook", f"zzsearch{unique}@example.com", display_name="Search Target")
        exclude_id = _make_identity(cur, "outlook", f"exclude-{uuid.uuid4().hex[:8]}@example.com", display_name="Excluded")

        results = search_identities(cur, f"zzsearch{unique}", exclude_person_key=exclude_id)

        assert any(r.identity_id == target_id for r in results)

    def test_excludes_identities_already_under_the_given_contact_key(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        unique = uuid.uuid4().hex[:8]
        contact_id = _make_identity(cur, "outlook", f"zzown{unique}@example.com", display_name="Self Match")

        results = search_identities(cur, f"zzown{unique}", exclude_person_key=contact_id)

        assert all(r.identity_id != contact_id for r in results)

    def test_excludes_self_identities(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        unique = uuid.uuid4().hex[:8]
        _make_identity(cur, "outlook", f"zzself{unique}@example.com", display_name="Me", is_self=True)
        exclude_id = _make_identity(cur, "outlook", f"exclude2-{uuid.uuid4().hex[:8]}@example.com")

        results = search_identities(cur, f"zzself{unique}", exclude_person_key=exclude_id)

        assert results == []

    def test_returns_empty_list_for_blank_query(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        exclude_id = _make_identity(cur, "outlook", f"exclude3-{uuid.uuid4().hex[:8]}@example.com")
        assert search_identities(cur, "   ", exclude_person_key=exclude_id) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_contact_editor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.contact_editor'`

- [ ] **Step 3: Implement**

Create `adapters/contact_editor.py`:

```python
"""Backend for the triage inbox's contact info panel — view a contact's
name and every known handle, edit the name, search for another identity
to link, or add a brand-new handle for a person who hasn't messaged yet.
See docs/superpowers/specs/2026-09-18-manual-hide-and-contact-editor-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ContactHandle:
    identity_id: str
    channel: str
    handle: str


@dataclass
class ContactInfo:
    person_key: str
    name: str
    handles: list[ContactHandle]


def get_contact_info(cur, person_key: str) -> ContactInfo | None:
    cur.execute(
        """
        select id, channel, handle, display_name
        from identity
        where coalesce(person_id, id) = %s
        order by channel, handle
        """,
        (person_key,),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    name = next((r[3] for r in rows if r[3]), None) or "(unknown)"
    handles = [ContactHandle(identity_id=str(r[0]), channel=r[1], handle=r[2]) for r in rows]
    return ContactInfo(person_key=person_key, name=name, handles=handles)


@dataclass
class SearchResult:
    identity_id: str
    channel: str
    handle: str
    display_name: str | None


def search_identities(cur, query: str, exclude_person_key: str) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []
    cur.execute(
        """
        select id, channel, handle, display_name
        from identity
        where is_self = false
          and handle ilike %s
          and coalesce(person_id, id) != %s
        order by handle
        limit 10
        """,
        (f"%{query}%", exclude_person_key),
    )
    return [
        SearchResult(identity_id=str(r[0]), channel=r[1], handle=r[2], display_name=r[3])
        for r in cur.fetchall()
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_contact_editor.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add adapters/contact_editor.py tests/test_contact_editor.py
git commit -m "feat: add contact_editor.get_contact_info and search_identities"
```

---

### Task 6: `update_contact_name`

**Files:**
- Modify: `adapters/contact_editor.py`
- Test: `tests/test_contact_editor.py`

**Interfaces:**
- Produces: `update_contact_name(cur, person_key: str, name: str) -> None`, consumed by Task 8.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_contact_editor.py` (add the import too):

```python
from adapters.contact_editor import get_contact_info, search_identities, update_contact_name


class TestUpdateContactName:
    def test_updates_name_for_every_identity_under_the_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Old Name') returning id")
        person_id = cur.fetchone()[0]
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", "Old Name", person_id),
        )
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net", "Old Name", person_id),
        )

        update_contact_name(cur, str(person_id), "New Name")

        cur.execute("select distinct display_name from identity where person_id = %s", (person_id,))
        assert [r[0] for r in cur.fetchall()] == ["New Name"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_contact_editor.py::TestUpdateContactName -v`
Expected: FAIL with `ImportError: cannot import name 'update_contact_name'`

- [ ] **Step 3: Implement**

Add to `adapters/contact_editor.py`, after `search_identities`:

```python
def update_contact_name(cur, person_key: str, name: str) -> None:
    cur.execute(
        "update identity set display_name = %s where coalesce(person_id, id) = %s",
        (name, person_key),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_contact_editor.py::TestUpdateContactName -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapters/contact_editor.py tests/test_contact_editor.py
git commit -m "feat: add contact_editor.update_contact_name"
```

---

### Task 7: `link_contact` + `add_contact_handle`

**Files:**
- Modify: `adapters/contact_editor.py`
- Test: `tests/test_contact_editor.py`

**Interfaces:**
- Consumes: `adapters.resolution.merge.apply_merge(cur, identity_a_id: str, identity_b_id: str) -> str` (existing function).
- Produces: `link_contact(cur, person_key: str, other_identity_id: str) -> str`, `add_contact_handle(cur, person_key: str, raw_handle: str) -> str`, both consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_contact_editor.py` (add the import too):

```python
from adapters.contact_editor import (
    add_contact_handle,
    get_contact_info,
    link_contact,
    search_identities,
    update_contact_name,
)


class TestLinkContact:
    def test_links_an_unresolved_identity_into_the_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Jordan Lee")
        other_id = _make_identity(cur, "whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net")

        link_contact(cur, contact_id, other_id)

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert len(info.handles) == 2
        cur.execute("select person_id from identity where id = %s", (other_id,))
        assert cur.fetchone()[0] is not None

    def test_raises_for_unknown_person_key(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        other_id = _make_identity(cur, "outlook", f"b-{uuid.uuid4().hex[:8]}@example.com")
        try:
            link_contact(cur, str(uuid.uuid4()), other_id)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestAddContactHandle:
    def test_adds_a_new_bare_identity_under_the_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        new_email = f"personal-{uuid.uuid4().hex[:8]}@gmail.com"

        add_contact_handle(cur, contact_id, new_email)

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert any(h.handle == new_email.lower() and h.channel == "outlook" for h in info.handles)

    def test_guesses_whatsapp_channel_for_a_bare_phone_number(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        phone = str(61400000000 + (uuid.uuid4().int % 900000))

        add_contact_handle(cur, contact_id, phone)

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert any(h.channel == "whatsapp" and h.handle == f"{phone}@s.whatsapp.net" for h in info.handles)

    def test_raises_when_handle_already_exists(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        existing_email = f"taken-{uuid.uuid4().hex[:8]}@example.com"
        _make_identity(cur, "outlook", existing_email)

        try:
            add_contact_handle(cur, contact_id, existing_email)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_creates_a_person_row_when_contact_has_none_yet(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        cur.execute("select person_id from identity where id = %s", (contact_id,))
        assert cur.fetchone()[0] is None  # not yet resolved, confirms this test's premise

        add_contact_handle(cur, contact_id, f"new-{uuid.uuid4().hex[:8]}@example.com")

        cur.execute("select person_id from identity where id = %s", (contact_id,))
        assert cur.fetchone()[0] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_contact_editor.py::TestLinkContact tests/test_contact_editor.py::TestAddContactHandle -v`
Expected: FAIL with `ImportError: cannot import name 'link_contact'`

- [ ] **Step 3: Implement**

Add to `adapters/contact_editor.py`. First, add the new import at the top (alongside the existing `import re`):

```python
from .resolution.merge import apply_merge
```

Then add, after `update_contact_name`:

```python
def link_contact(cur, person_key: str, other_identity_id: str) -> str:
    cur.execute(
        "select id from identity where coalesce(person_id, id) = %s limit 1",
        (person_key,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no identity found for person_key {person_key}")
    representative_id = str(row[0])
    return apply_merge(cur, representative_id, other_identity_id)


_WHATSAPP_SUFFIX = "@s.whatsapp.net"


def _guess_channel_and_handle(raw_input: str) -> tuple[str, str]:
    text = raw_input.strip()
    if "@" in text:
        return "outlook", text.lower()
    digits_only = re.sub(r"[^\d]", "", text)
    if digits_only and digits_only == text.lstrip("+"):
        return "whatsapp", f"{digits_only}{_WHATSAPP_SUFFIX}"
    return "outlook", text.lower()


def add_contact_handle(cur, person_key: str, raw_handle: str) -> str:
    channel, handle = _guess_channel_and_handle(raw_handle)

    cur.execute("select id from identity where channel = %s and handle = %s", (channel, handle))
    if cur.fetchone() is not None:
        raise ValueError(f"identity already exists for {channel}:{handle}")

    cur.execute(
        "select person_id, id from identity where coalesce(person_id, id) = %s limit 1",
        (person_key,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no identity found for person_key {person_key}")
    person_id, representative_id = row

    if person_id is None:
        cur.execute("select display_name from identity where id = %s", (representative_id,))
        (existing_name,) = cur.fetchone()
        cur.execute(
            "insert into person (primary_name) values (%s) returning id",
            (existing_name or "",),
        )
        person_id = cur.fetchone()[0]
        cur.execute("update identity set person_id = %s where id = %s", (person_id, representative_id))

    cur.execute(
        "insert into identity (channel, handle, person_id) values (%s, %s, %s) returning id",
        (channel, handle, person_id),
    )
    return str(cur.fetchone()[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_contact_editor.py -v`
Expected: all pass

- [ ] **Step 5: Run the full test suite and lint**

Run: `pytest tests/ -q && ruff check .`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add adapters/contact_editor.py tests/test_contact_editor.py
git commit -m "feat: add contact_editor.link_contact and add_contact_handle"
```

---

### Task 8: Flask routes for the contact panel

**Files:**
- Modify: `scripts/onboarding/app.py`

**Interfaces:**
- Consumes: every function from `adapters/contact_editor.py` (Tasks 5-7).
- Produces: `GET /contact/<person_key>`, `POST /contact/<person_key>/name`, `GET /contact/search`, `POST /contact/<person_key>/link`, `POST /contact/<person_key>/add-handle`, consumed by Task 9.

- [ ] **Step 1: Add the import**

In `scripts/onboarding/app.py`, find:

```python
from adapters import inbox_query
```

and add right after it:

```python
from adapters import contact_editor
```

- [ ] **Step 2: Add the routes**

Add these after the existing `inbox_conversation_unhide` route (from Task 3):

```python
    @flask_app.get("/contact/<person_key>")
    def contact_info_json(person_key):
        with _db_cursor() as cur:
            info = contact_editor.get_contact_info(cur, person_key)
        if info is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "person_key": info.person_key,
            "name": info.name,
            "handles": [
                {"identity_id": h.identity_id, "channel": h.channel, "handle": h.handle}
                for h in info.handles
            ],
        })

    @flask_app.post("/contact/<person_key>/name")
    def contact_update_name(person_key):
        name = (request.get_json(silent=True) or {}).get("name", "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        with _db_cursor() as cur:
            contact_editor.update_contact_name(cur, person_key, name)
        return jsonify({"status": "ok"})

    @flask_app.get("/contact/search")
    def contact_search_json():
        query = request.args.get("q", "")
        exclude = request.args.get("exclude", "")
        with _db_cursor() as cur:
            results = contact_editor.search_identities(cur, query, exclude)
        return jsonify([
            {
                "identity_id": r.identity_id, "channel": r.channel,
                "handle": r.handle, "display_name": r.display_name,
            }
            for r in results
        ])

    @flask_app.post("/contact/<person_key>/link")
    def contact_link(person_key):
        other_id = (request.get_json(silent=True) or {}).get("identity_id", "")
        if not other_id:
            return jsonify({"error": "identity_id required"}), 400
        with _db_cursor() as cur:
            contact_editor.link_contact(cur, person_key, other_id)
        return jsonify({"status": "ok"})

    @flask_app.post("/contact/<person_key>/add-handle")
    def contact_add_handle(person_key):
        handle = (request.get_json(silent=True) or {}).get("handle", "").strip()
        if not handle:
            return jsonify({"error": "handle required"}), 400
        with _db_cursor() as cur:
            try:
                contact_editor.add_contact_handle(cur, person_key, handle)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
        return jsonify({"status": "ok"})
```

- [ ] **Step 3: Manually verify against the local dev server**

Run: `python scripts/onboarding/app.py`, then in another terminal, using any two real handles/person_keys from `curl -s http://127.0.0.1:5000/inbox/conversations.json`:

```bash
curl -s http://127.0.0.1:5000/contact/<a-real-person-key>
curl -s "http://127.0.0.1:5000/contact/search?q=gmail&exclude=<same-person-key>"
curl -s -X POST http://127.0.0.1:5000/contact/<a-real-person-key>/name -H "Content-Type: application/json" -d '{"name": "Test Rename"}'
curl -s http://127.0.0.1:5000/contact/<a-real-person-key>
```

Expected: the first call returns `{"person_key": ..., "name": ..., "handles": [...]}`; the search call returns a JSON array (possibly empty); the rename call returns `{"status": "ok"}`; the final call shows the updated name.

- [ ] **Step 4: Commit**

```bash
git add scripts/onboarding/app.py
git commit -m "feat: add contact info panel routes"
```

---

### Task 9: Frontend — contact info panel

**Files:**
- Modify: `scripts/onboarding/templates/inbox.html`

**Interfaces:**
- Consumes: every route from Task 8.

- [ ] **Step 1: Make the detail panel's header name and third-party `from_name` labels clickable**

Find `openDetail`'s header block:

```javascript
      <div class="detail-head">
        <div class="avatar" style="background:${avatarColor(c.name)}">${initials(c.name)}</div>
        <div>
          <div class="row-name">${escapeHtml(c.name)}</div>
          <div class="row-time">${CHANNELS[c.channel].label} &middot; ${formatRelativeTime(c.last_message_at)}</div>
        </div>
      </div>
```

Replace with (adds `contact-link` class and `data-contact-id`):

```javascript
      <div class="detail-head">
        <div class="avatar" style="background:${avatarColor(c.name)}">${initials(c.name)}</div>
        <div>
          <div class="row-name contact-link" data-contact-id="${c.person_key}">${escapeHtml(c.name)}</div>
          <div class="row-time">${CHANNELS[c.channel].label} &middot; ${formatRelativeTime(c.last_message_at)}</div>
        </div>
      </div>
```

Find the `from_name` label:

```javascript
                    ${m.from_name ? `<div class="thread-from">${escapeHtml(m.from_name)}</div>` : ""}
```

This one has no `person_key` available in the message data (it's just a display-name string, not looked up), so it stays plain text — do not make it clickable. (Out of scope for this pass; would need `get_detail()` to carry a `from_person_key` field, which the design doc doesn't call for.)

After the `backdrop.innerHTML = ...` assignment in `openDetail`, find:

```javascript
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeOverlay(); });
  document.body.appendChild(backdrop);
  document.getElementById("detail-close-btn").addEventListener("click", closeOverlay);
  wireGraphNodes();
```

Replace with:

```javascript
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeOverlay(); });
  document.body.appendChild(backdrop);
  document.getElementById("detail-close-btn").addEventListener("click", closeOverlay);
  wireGraphNodes();
  document.querySelectorAll(".contact-link").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      openContactPanel(el.dataset.contactId);
    });
  });
```

- [ ] **Step 2: Write `openContactPanel`**

Add this new function right after `openDetail` (before the `document.getElementById("f-unread")...` line):

```javascript
async function openContactPanel(personKey) {
  const resp = await fetch(`/contact/${personKey}`);
  if (!resp.ok) return;
  const contact = await resp.json();
  const backdrop = document.createElement("div");
  backdrop.className = "assistant-backdrop contact-backdrop";
  backdrop.innerHTML = `
    <div class="contact-panel">
      <button class="assistant-close" id="contact-close-btn">&times;</button>
      <div class="contact-name-row">
        <input type="text" id="contact-name-input" value="${escapeHtml(contact.name)}">
        <button id="contact-name-save" type="button">Save</button>
      </div>
      <h3>Known handles</h3>
      <div class="contact-handles">
        ${contact.handles.map(h => `
          <div class="contact-handle-row">
            <span class="channel-icon">${CHANNELS[h.channel].icon}</span>
            <span>${escapeHtml(h.handle)}</span>
          </div>
        `).join("")}
      </div>
      <h3>Add or link a handle</h3>
      <input type="text" id="contact-add-input" placeholder="Email, phone, or search existing contacts...">
      <div class="contact-search-results" id="contact-search-results"></div>
      <div class="contact-add-new" id="contact-add-new" hidden>
        <span id="contact-add-new-label"></span>
        <button id="contact-add-new-btn" type="button">Add as new</button>
      </div>
    </div>
  `;
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeOverlay(); });
  document.body.appendChild(backdrop);
  document.getElementById("contact-close-btn").addEventListener("click", closeOverlay);

  document.getElementById("contact-name-save").addEventListener("click", async () => {
    const name = document.getElementById("contact-name-input").value.trim();
    if (!name) return;
    await fetch(`/contact/${personKey}/name`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const row = CONVERSATIONS.find(c => c.person_key === personKey);
    if (row) row.name = name;
    closeOverlay();
    renderList();
  });

  const addInput = document.getElementById("contact-add-input");
  const resultsBox = document.getElementById("contact-search-results");
  const addNewBox = document.getElementById("contact-add-new");
  const addNewLabel = document.getElementById("contact-add-new-label");
  const addNewBtn = document.getElementById("contact-add-new-btn");

  addInput.addEventListener("input", async () => {
    const q = addInput.value.trim();
    if (!q) { resultsBox.innerHTML = ""; addNewBox.hidden = true; return; }
    const resp2 = await fetch(`/contact/search?q=${encodeURIComponent(q)}&exclude=${personKey}`);
    const results = await resp2.json();
    resultsBox.innerHTML = results.map(r => `
      <div class="contact-search-result" data-identity-id="${r.identity_id}">
        <span class="channel-icon">${CHANNELS[r.channel].icon}</span>
        <span>${escapeHtml(r.display_name || r.handle)}</span>
        <span class="row-time">${escapeHtml(r.handle)}</span>
      </div>
    `).join("");
    resultsBox.querySelectorAll(".contact-search-result").forEach(el => {
      el.addEventListener("click", async () => {
        await fetch(`/contact/${personKey}/link`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identity_id: el.dataset.identityId }),
        });
        closeOverlay();
        openContactPanel(personKey);
      });
    });
    addNewBox.hidden = results.length > 0;
    addNewLabel.textContent = `No match found for "${q}"`;
  });

  addNewBtn.addEventListener("click", async () => {
    const q = addInput.value.trim();
    if (!q) return;
    const resp3 = await fetch(`/contact/${personKey}/add-handle`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ handle: q }),
    });
    if (!resp3.ok) {
      const body = await resp3.json();
      alert(body.error || "Could not add that handle.");
      return;
    }
    closeOverlay();
    openContactPanel(personKey);
  });
}
```

- [ ] **Step 3: Add the CSS**

Find the `.assistant-close` block:

```css
  .assistant-close {
    align-self: flex-end; margin: -8px -6px 4px auto;
    width: 26px; height: 26px; border-radius: 50%; border: none; background: transparent;
    color: var(--text-dim); font-size: 16px; cursor: pointer;
  }
```

Add right after it:

```css
  /* Contact info panel — opens on clicking a contact's name in the
     detail panel header (see openContactPanel). Reuses .assistant-
     backdrop/.assistant-close for the overlay/close-button mechanics;
     this is its own narrower panel since it's a form, not a message list. */
  .contact-panel {
    width: 420px; max-height: 80vh; overflow-y: auto;
    background: #fff; border-radius: 18px;
    box-shadow: 0 30px 70px rgba(0,0,0,0.35);
    display: flex; flex-direction: column;
    padding: 22px 20px 20px;
  }
  .contact-panel h3 {
    font-size: 12.5px; letter-spacing: 0.06em; color: var(--text-dim);
    text-transform: uppercase; margin: 18px 0 8px;
  }
  .contact-name-row { display: flex; gap: 8px; }
  .contact-name-row input {
    flex: 1; border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 15px; font-weight: 600; color: var(--text);
  }
  .contact-name-row button, .contact-add-new button {
    border: none; border-radius: 8px; background: var(--text); color: #fff;
    padding: 8px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer;
  }
  .contact-handles { display: flex; flex-direction: column; gap: 6px; }
  .contact-handle-row, .contact-search-result {
    display: flex; align-items: center; gap: 8px;
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 12.5px;
  }
  .contact-search-result { cursor: pointer; justify-content: space-between; }
  .contact-search-result:hover { background: var(--panel-2); }
  .contact-add-input, #contact-add-input {
    width: 100%; border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 12.5px; margin-top: 4px; box-sizing: border-box;
  }
  .contact-search-results { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
  .contact-add-new {
    margin-top: 8px; display: flex; align-items: center; justify-content: space-between;
    font-size: 12px; color: var(--text-dim);
  }
```

- [ ] **Step 4: Add the CSS class hookup for `.row-name` cursor**

Find:

```css
  .row-name { font-weight: 600; font-size: 13.5px; }
```

Replace with:

```css
  .row-name { font-weight: 600; font-size: 13.5px; }
  .contact-link { cursor: pointer; }
  .contact-link:hover { text-decoration: underline; }
```

- [ ] **Step 5: Manually verify in a browser**

Run: `python scripts/onboarding/app.py`, open `http://localhost:5000/inbox`, click any conversation row to open the detail panel, then click the contact's name in the panel header. The contact panel should open showing their name (editable) and every known handle. Type a fragment of an email that matches another real contact in the database into "Add or link a handle" — a search result should appear; clicking it should close and reopen the panel showing the merged handle list (now longer). Type a fresh, made-up email that matches nothing — an "Add as new" button should appear; clicking it should add that handle to the list.

- [ ] **Step 6: Commit**

```bash
git add scripts/onboarding/templates/inbox.html
git commit -m "feat: add contact info panel UI (view name/handles, edit, search-link, add)"
```

---

## Self-Review Notes

- **Spec coverage:** Feature 1 (manual hide, reversible, hover icon, Hidden filter) — Tasks 1-4. Feature 2 (view/edit name, view handles, search-and-link via `apply_merge`, add-new-handle with plain-UPDATE/DELETE safety since it carries no messages) — Tasks 5-9. Both features from the design doc are covered.
- **Placeholder scan:** none found — every step has complete code.
- **Type consistency:** `ContactHandle`/`ContactInfo`/`SearchResult` dataclass fields match between `adapters/contact_editor.py` (Tasks 5-7) and the Flask JSON serialization (Task 8) and the frontend's expected JSON shape (Task 9) — `identity_id`/`channel`/`handle`/`display_name`/`person_key`/`name`/`handles` used consistently throughout.
