-- Contacts ingest (build plan §8's bridge source, Block A scope per §14 —
-- "contacts ingest" is listed as Block A work; actually *using* this data
-- to link identities is Block B's "resolution v1 with the contacts
-- bridge"). This table is just the raw ingested record — no matching
-- logic lives here.
--
-- Probed against the real mailbox (2026-08-27): both /me/contacts and
-- /me/people returned 0 results. This table exists and is wired up
-- anyway, per §14's Block A scope — an empty table today, real data the
-- moment a mailbox that actually has contacts saved gets connected.

create table graph_contact (
    id           text primary key,        -- Graph's own contact id
    display_name text,
    emails       text[] not null default '{}',  -- lowercased, adapter-normalised
    phones       text[] not null default '{}',  -- digits only, no '+' or
                                                   -- separators — matches the
                                                   -- numeric part of a WhatsApp
                                                   -- jid (e.g. 15806709090),
                                                   -- not full E.164
    synced_at    timestamptz not null default now()
);
