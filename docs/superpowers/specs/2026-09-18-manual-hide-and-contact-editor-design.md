# Manual Hide + Contact Editor — Design

## Feature 1: Manually hide a conversation

### Goal

Let Eva hide a specific conversation from the triage inbox list herself,
independent of the automatic hide rules (stale-unknown, automated-sender,
bulk-recipient, empty-body). Reversible — a hidden conversation can be
found and unhidden.

### Data model

New table:

```sql
create table contact_hidden (
    contact_key uuid primary key,
    hidden_at   timestamptz not null default now()
);
```

`contact_key` is the same `coalesce(person_id, id)` value used
everywhere else (`contact_stats`, `contact_last_message`) — not a
foreign key to `identity` directly, since a contact_key doesn't always
correspond to one physical row.

### Query layer

`list_conversations(cur, show_hidden: bool = False)`:
- Default (`show_hidden=False`): add `and cs.contact_key not in (select contact_key from contact_hidden)` to the existing filter set.
- `show_hidden=True`: filter to *only* rows in `contact_hidden` instead (mirrors how a future "Hidden" checkbox behaves — same shape as the existing Unread/Unanswered/Has draft ready filters, which are also "show only matching," not exclusion toggles).

Two new functions:
- `hide_contact(cur, contact_key: str) -> None` — upsert into `contact_hidden`.
- `unhide_contact(cur, contact_key: str) -> None` — delete from `contact_hidden`.

### API routes (`scripts/onboarding/app.py`)

- `POST /inbox/conversation/<person_key>/hide`
- `POST /inbox/conversation/<person_key>/unhide`
- `GET /inbox/conversations.json?hidden=1` — passes `show_hidden=True` through to `list_conversations`.

### Frontend

- A hide icon (eye-slash) appears on hover over a conversation row, next to the channel icon — click calls the hide endpoint and removes the row from the current list without a reload.
- A new "Hidden" checkbox in the existing FILTER BY panel, same visual style as Unread/Unanswered/Has draft ready. Checking it re-fetches with `hidden=1`; each row in that view shows an "Unhide" button instead of the hide icon.

---

## Feature 2: Contact info panel (view + edit + link)

### Goal

Clicking a sender's name (in the conversation list or the detail panel)
opens a small panel: view every known handle (email/phone/profile) for
that contact, edit the display name, and search-and-link another
identity that hasn't been merged in yet — a lighter-weight, inline
alternative to opening `/resolution` for a merge Eva already knows is
correct because she's looking straight at the contact.

### Opening the panel

- Click a contact's name anywhere it's rendered as a link (conversation
  list row, detail panel header, a `from_name` label on a third-party
  message bubble) → opens the panel for that `person_key`.
- Works as a pure viewer when Eva makes no edits — just closes.

### Panel contents

- **Name** — editable text field, current value from `identity.display_name` (aggregated the same way `get_detail()` already does: `max(display_name)` across the contact's identities).
- **Known handles** — a list of every `identity.handle` under this `contact_key`, each labeled with its channel (Outlook/WhatsApp/LinkedIn icon, matching existing conventions).
- **Add handle** field — free-text input (email or phone). As Eva types, live-search `identity` for existing rows matching the input (substring match on `handle`, excluding identities already under this contact_key and excluding `is_self` rows) — same kind of query `/resolution`'s existing search already does, reused rather than re-implemented if it already supports this shape.
  - **A search result exists and Eva clicks it** → this is a real merge: call `apply_merge()` (the same reversible function `/resolution` uses, already logging to `merge_log` for undo — see `adapters/resolution/merge.py`). This pulls the other identity's full message history into this contact.
  - **No search result, Eva chooses to add it anyway** → creates a brand-new `identity` row for that handle (channel guessed from the input's shape — `@` present → whichever channel makes sense, phone-shaped digits → whatsapp; ambiguous cases default to `outlook` since that's the only channel where a bare-email manual entry makes sense) with no message history, `person_id` set to match this contact (creating a `person` row first if this contact_key is still a single unmerged identity with no `person_id` yet). Because it carries zero messages, editing or deleting this row later is a **plain UPDATE/DELETE** — no `merge_log`/undo machinery involved, since there's no message data at stake. This directly answers Eva's typo-recovery worry: a manual entry is cheap to fix.

### Saving a name edit

Updates `identity.display_name` for every identity row under this
`contact_key` (not just one), so the aggregated `max(display_name)`
views stay consistent regardless of which underlying handle Eva looked
at when she opened the panel.

### API routes

- `GET /contact/<person_key>` — panel data: name, handle list, (no
  search results server-side; search is its own endpoint below).
- `POST /contact/<person_key>/name` — `{name: str}`, updates display_name
  across the cluster.
- `GET /contact/search?q=<text>&exclude=<person_key>` — live search for
  the "add handle" field.
- `POST /contact/<person_key>/link` — `{identity_id: str}` → calls
  `apply_merge()`.
- `POST /contact/<person_key>/add-handle` — `{handle: str, channel: str}`
  → creates the new bare identity as described above.

### Out of scope (explicitly deferred)

- Deleting/editing a handle that already has real message history through
  this panel (that's `/resolution`'s undo_merge territory, not this
  panel's).
- Editing anything other than name + handles (no phone-number-format
  validation, no company field, etc.) this pass.
