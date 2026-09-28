-- Latest refresh outcome is independent of the last successful cached brief.
-- person_key may be an identity or person UUID, as in ai_brief itself.
create table if not exists ai_brief_status (
    person_key uuid primary key,
    status text not null check (status in ('success', 'truncated', 'skipped', 'failed')),
    error_code text check (error_code in (
        'input_budget_exceeded', 'token_count_failed', 'provider_failed',
        'invalid_response', 'storage_failed'
    )),
    model text not null,
    input_tokens integer check (input_tokens >= 0),
    original_input_tokens integer check (original_input_tokens >= 0),
    omitted_messages integer not null default 0 check (omitted_messages >= 0),
    truncated_text boolean not null default false,
    attempted_at timestamptz not null default now()
);

comment on table ai_brief_status is
    'Latest brief attempt; fixed outcome codes only, never provider errors or source message text.';
