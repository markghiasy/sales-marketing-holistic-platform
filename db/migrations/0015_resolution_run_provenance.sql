create table resolution_run (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  code_revision text not null,
  status text not null default 'running',
  results jsonb not null default '[]'
);
alter table link_candidate add column run_id uuid references resolution_run(id);
alter table link_candidate add column rule_version text;
create index on link_candidate(run_id);
create function attribute_candidate_run() returns trigger language plpgsql as $$
begin
  new.run_id := coalesce(new.run_id, nullif(current_setting('ironman.resolution_run', true),'')::uuid);
  new.rule_version := coalesce(new.rule_version, nullif(current_setting('ironman.rule_version',true),''));
  return new;
end $$;
create trigger candidate_run_provenance before insert on link_candidate
for each row execute function attribute_candidate_run();
