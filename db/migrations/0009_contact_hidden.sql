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
