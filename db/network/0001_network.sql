-- Derived state only. Run via network_schema; never part of source migrations.
create schema network;
create table network.state (
    singleton boolean primary key default true check(singleton),
    schema_version integer not null,
    binding text not null,
    owner_id text not null,
    version bigint not null default 0,
    cursor jsonb,
    last_success_at timestamptz,
    source_checked_at timestamptz,
    error_code text,
    schedules jsonb not null default '{}'
);
create table network.source_record (
    key text primary key,
    kind text not null,
    source_id text not null,
    fingerprint text not null,
    payload jsonb not null,
    unique(kind, source_id)
);
create table network.item (
    kind text not null,
    id text not null,
    entity_ids text[] not null,
    payload jsonb not null,
    fingerprint text not null,
    search_text text not null,
    search_vector tsvector generated always as (to_tsvector('simple', search_text)) stored,
    primary key(kind,id)
);
create index network_item_entities on network.item using gin(entity_ids);
create index network_item_search on network.item using gin(search_vector);
create table network.dependency (
    item_kind text not null,
    item_id text not null,
    source_key text not null,
    fingerprint text not null,
    primary key(item_kind,item_id,source_key),
    foreign key(item_kind,item_id) references network.item(kind,id) on delete cascade
);
create index network_dependency_source on network.dependency(source_key);
create table network.proposal (
    id text primary key,
    fingerprint text not null unique,
    payload jsonb not null,
    dependencies jsonb not null,
    status text not null default 'pending' check(status in ('pending','confirmed','rejected')),
    created_at timestamptz not null default now()
);
create table network.review_event (
    id bigserial primary key,
    proposal_id text not null,
    decision text not null check(decision in ('confirm','reject')),
    payload jsonb not null,
    at timestamptz not null default now()
);
