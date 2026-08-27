-- LinkedIn connections ingest (§8's Rule 5 material: "name plus
-- organisation correlation for LinkedIn... writes a link_candidate for
-- human review"). Company name is the useful signal here, not email —
-- real archive checked 2026-08-28: 935 connections, only 25 (2.7%) carry
-- an email address at all (LinkedIn only includes it if the connection
-- opted into sharing), but 890 (95%) carry a company name. This table is
-- just the raw ingested record — no matching logic, that's Block B.
--
-- Unlike every other Block A ingest, this data can only ever be a
-- snapshot, not a live sync: it comes from LinkedIn's official data
-- export, a manual request with a ~24h turnaround and no push/webhook to
-- drive off of (same constraint export_sync.py already works under for
-- messages). Re-running this ingest means re-requesting a fresh archive,
-- not polling for new rows.

create table linkedin_connection (
    id            text primary key,  -- profile URL, lowercased; falls back
                                       -- to "name:<lowercased name>" for the
                                       -- rare row with no URL (same scheme
                                       -- export_sync.py's _handle() uses)
    first_name    text,
    last_name     text,
    profile_url   text,
    email         text,              -- sparse — see comment above
    company       text,
    position      text,
    connected_on  date,
    synced_at     timestamptz not null default now()
);
