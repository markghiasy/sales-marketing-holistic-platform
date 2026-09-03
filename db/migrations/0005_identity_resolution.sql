-- db/migrations/0005_identity_resolution.sql
-- Identity resolution (§8) + Phase 1 knowledge-graph facts (§10 upgrade).
-- See docs/superpowers/specs/2026-09-03-identity-resolution-design.md.

alter table person add column preferred_name text;
alter table link_candidate add column reason text;

create table organization (
    id            uuid primary key default gen_random_uuid(),
    canonical_name text not null unique  -- normalised: lowercase, trimmed,
                                          -- common suffix stripped
);

create table fact (
    id                 uuid primary key default gen_random_uuid(),
    subject_identity_id uuid not null references identity(id),
    fact_type          text not null,                       -- closed vocabulary,
                                                              -- see adapters/resolution/facts.py
    object_text        text,                                -- fallback for values with
                                                              -- no canonical entity yet
    object_identity_id uuid references identity(id),         -- set when the object is
                                                              -- also an identity
    object_org_id      uuid references organization(id),     -- set when the object is
                                                              -- an organisation
    confidence         real not null,
    source             text not null,                        -- e.g. 'linkedin_connection'
    source_message_id  uuid references message(id),           -- null for structured-source facts
    status             text not null default 'pending',       -- 'pending' | 'confirmed' | 'rejected'
    reason             text,
    model              text,                                  -- null until Phase 2
    prompt_version     text,                                  -- null until Phase 2
    extracted_at       timestamptz not null default now(),
    reviewed_at        timestamptz
);

create index on fact (subject_identity_id);
create index on fact (status);
create index on link_candidate (status);
