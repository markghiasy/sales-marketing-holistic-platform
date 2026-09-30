-- Candidate topology changes are rare: conservatively invalidate all briefs.
-- Message/fact changes invalidate only dependent identities, without paid calls.
create table identity_cluster_revision (singleton boolean primary key default true check(singleton), revision bigint not null);
insert into identity_cluster_revision values (true, 0);
create function current_identity_cluster_revision() returns bigint language sql stable as $$
  select revision from identity_cluster_revision where singleton
$$;
alter table identity add column context_version bigint not null default 0;
alter table ai_brief add column candidate_revision bigint not null default -1;
alter table ai_brief alter column candidate_revision set default current_identity_cluster_revision();
create table ai_brief_dependency (
  person_key uuid not null references ai_brief(person_key) on delete cascade on update cascade,
  identity_id uuid not null references identity(id),
  context_version bigint not null,
  primary key (person_key, identity_id)
);
create index on ai_brief_dependency(identity_id);

create function bump_candidate_revision() returns trigger language plpgsql as $$
begin
  update identity_cluster_revision set revision=revision+1 where singleton;
  return null;
end $$;
create trigger candidate_revision_changed after insert or update or delete on link_candidate
for each statement execute function bump_candidate_revision();
create trigger hidden_identity_changed after insert or update or delete on contact_hidden
for each statement execute function bump_candidate_revision();

create function bump_identity_context() returns trigger language plpgsql as $$
begin
  if (new.person_id,new.display_name,new.is_self) is distinct from
     (old.person_id,old.display_name,old.is_self) then
    new.context_version := old.context_version+1;
  end if;
  return new;
end $$;
create trigger identity_context_changed before update on identity
for each row execute function bump_identity_context();

create function bump_identity_topology() returns trigger language plpgsql as $$
begin
  if TG_OP = 'INSERT' then
    if new.person_id is not null then
      update identity_cluster_revision set revision=revision+1 where singleton;
    end if;
  elsif (new.person_id,new.is_self) is distinct from (old.person_id,old.is_self) then
    update identity_cluster_revision set revision=revision+1 where singleton;
  end if;
  return null;
end $$;
create trigger identity_topology_changed after insert or update of person_id,is_self on identity
for each row execute function bump_identity_topology();

create function bump_participant_context() returns trigger language plpgsql as $$
begin
  if TG_OP <> 'INSERT' then
    update identity set context_version=context_version+1 where id=old.identity_id;
  end if;
  if TG_OP <> 'DELETE' then
    update identity set context_version=context_version+1 where id=new.identity_id;
  end if;
  return null;
end $$;
create trigger participant_context_changed after insert or update or delete on message_participant
for each row execute function bump_participant_context();

create function bump_message_context() returns trigger language plpgsql as $$
begin
  update identity set context_version=context_version+1 where id in
    (select identity_id from message_participant where message_id=old.id);
  return null;
end $$;
create trigger message_context_changed after update or delete on message
for each row execute function bump_message_context();

create function bump_fact_context() returns trigger language plpgsql as $$
begin
  if TG_OP <> 'INSERT' then
    update identity set context_version=context_version+1 where id=old.subject_identity_id;
  end if;
  if TG_OP <> 'DELETE' then
    update identity set context_version=context_version+1 where id=new.subject_identity_id;
  end if;
  return null;
end $$;
create trigger fact_context_changed after insert or update or delete on fact
for each row execute function bump_fact_context();

create view current_ai_brief as
select b.* from ai_brief b
where b.candidate_revision=current_identity_cluster_revision()
  and not exists (select 1 from ai_brief_dependency d join identity i on i.id=d.identity_id
                  where d.person_key=b.person_key and d.context_version<>i.context_version);
