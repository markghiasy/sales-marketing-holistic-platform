-- Comms & Outreach Platform — store schema
-- Source: build plan §7 ("The store schema"). Mirrors it field-for-field;
-- do not add columns here without updating that section first.

create extension if not exists pgcrypto;

create table person (
    id          uuid primary key default gen_random_uuid(),
    primary_name text not null,
    created_at  timestamptz not null default now(),
    merged_into uuid null references person(id)  -- soft merge: reversible, never delete rows
);

create table identity (
    id           uuid primary key default gen_random_uuid(),
    channel      text not null,                  -- 'outlook' | 'whatsapp' | 'linkedin'
    handle       text not null,                  -- normalised at the adapter: email lowercased,
                                                   -- phone E.164, LinkedIn member id
    display_name text,
    person_id    uuid null references person(id), -- null = not yet resolved
    is_self      boolean not null default false,  -- own handles; drives message.direction
    unique (channel, handle)
);

create table thread (
    id            uuid primary key default gen_random_uuid(),
    channel       text not null,
    external_id   text not null,                  -- Graph conversationId | chat id | conversation id
    title         text,
    is_group      boolean not null default false,
    last_message_at timestamptz,
    unique (channel, external_id)
);

create table message (
    id             uuid primary key default gen_random_uuid(),
    thread_id      uuid not null references thread(id),
    channel        text not null,
    external_id    text not null,                 -- see §6 warning: key on internetMessageId for
                                                    -- Outlook, NOT Graph's own `id` (not stable
                                                    -- across folder moves)
    direction      text not null,                  -- 'inbound' | 'outbound', computed against
                                                    -- identity.is_self at ingest, stored not derived
    sent_at        timestamptz not null,
    from_identity_id uuid references identity(id),
    subject        text,                           -- Outlook only. Null elsewhere — don't synthesise
    body_text      text not null,                  -- plain text, quoted-reply chains stripped
    is_automated   boolean not null default false,  -- set by parser tier 1 at ingest (§9)
    raw            jsonb not null,                  -- original payload, quarantined for debugging.
                                                     -- nothing downstream reads this column
    ingested_at    timestamptz not null default now(),
    unique (channel, external_id)                   -- idempotency key
);

create table message_participant (
    message_id  uuid not null references message(id),
    identity_id uuid not null references identity(id),
    role        text not null,                      -- 'from' | 'to' | 'cc' ...
    primary key (message_id, identity_id, role)
);
-- this table IS the network graph's edge table (§10) — direction and timestamps
-- already live on message; graph v1 is SQL views over this join, not a new store.

create table link_candidate (
    id           uuid primary key default gen_random_uuid(),
    identity_a_id uuid not null references identity(id),
    identity_b_id uuid not null references identity(id),
    score        real not null,
    method       text not null,                      -- how the candidate link was produced
    status       text not null default 'pending'      -- 'pending' | 'confirmed' | 'rejected'
);

create table action (
    id              uuid primary key default gen_random_uuid(),
    thread_id       uuid not null references thread(id),
    person_id       uuid references person(id),
    kind            text not null,                    -- 'owed_by_me' | 'owed_to_me'
    title           text not null,
    due_at          timestamptz,
    status          text not null default 'open',
    confidence      real not null,
    dedupe_key      text not null,                     -- stops the same commitment reappearing
                                                        -- as a thread develops
    model           text not null,
    prompt_version  text not null,
    extracted_at    timestamptz not null default now(),
    external_page_id text,                             -- the task-layer (Notion) record id
    verdict         text,                               -- the judgement signal — training data
                                                         -- for both agents
    verdict_at      timestamptz,
    edit_note       text
);

create table outreach (
    id                  uuid primary key default gen_random_uuid(),
    person_id           uuid not null references person(id),
    score               real not null,
    score_rationale     text not null,                  -- explainable, not a debug log
    relationship_context jsonb not null,                 -- last touch, channel, warmth
    draft_body          text,
    draft_version       int not null default 0,
    status              text not null default 'shortlisted',
                                                          -- shortlisted|draft_ready|approved|sent|replied
    verdict             text,
    edit_diff           text,
    sent_at             timestamptz,
    replied_at          timestamptz
);

create table event (
    id         bigserial primary key,
    at         timestamptz not null default now(),
    actor      text not null,
    kind       text not null,
    entity     text not null,
    entity_id  uuid,
    payload    jsonb
);

create index on message (thread_id);
create index on message (sent_at);
create index on message_participant (identity_id);
create index on identity (person_id);
create index on action (status);
create index on outreach (status);
