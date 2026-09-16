-- db/migrations/0007_inbox_real_data.sql
-- Real data for the triage inbox (Block C, STU-131).
-- See docs/superpowers/specs/2026-09-16-triage-inbox-real-data-llm-design.md.

-- No mailbox-sourced read state exists anywhere in this schema (Graph's
-- own isRead is only ever quarantined in message.raw, which nothing
-- reads by design — see 0001_init.sql's own comment on that column).
-- This is an app-local read signal instead: a thread is unread when its
-- last_message_at is newer than last_read_at (or last_read_at is null).
-- Backfilling existing data to "already read" (Eva's call) means today's
-- rows never show up unread just because this column is new.
alter table thread add column last_read_at timestamptz;
update thread set last_read_at = now();

-- Cache for the per-person LLM brief (design doc's "precompute, not
-- live" architecture decision) — one row per person_key, overwritten on
-- every regeneration rather than appended, since only the latest brief
-- is ever meaningful.
create table ai_brief (
    person_key      uuid primary key,
    summary         text not null,       -- short third-person action-summary,
                                          -- the list row's preview text
    context         jsonb not null,      -- array of first-person-voice full
                                          -- sentences
    topic           text not null,       -- short topic phrase for the list
                                          -- row's colored tag pill
    graph           jsonb not null,      -- {org: {name, blurb}|null,
                                          -- people: [{name, relation}]}
    urgency         smallint not null,   -- 1-3, same rough meaning as the
                                          -- old mock "priority"
    model           text not null,
    prompt_version  text not null,
    generated_at    timestamptz not null default now()
);
