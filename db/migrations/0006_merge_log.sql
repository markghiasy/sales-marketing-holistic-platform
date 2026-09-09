-- db/migrations/0006_merge_log.sql
-- Reversible identity merge + merge audit log.
-- See docs/superpowers/specs/2026-09-09-reversible-identity-merge-design.md.

create table merge_log (
    id                   uuid primary key default gen_random_uuid(),
    merged_at            timestamptz not null default clock_timestamp(),  -- NOT now():
                                                                            -- now() is frozen
                                                                            -- for the whole
                                                                            -- transaction, so
                                                                            -- two merges in one
                                                                            -- transaction would
                                                                            -- get an identical
                                                                            -- timestamp and the
                                                                            -- "later merge"
                                                                            -- check below could
                                                                            -- never fire
    identity_a_id        uuid not null references identity(id),
    identity_b_id        uuid not null references identity(id),
    survivor_person_id   uuid not null references person(id),
    absorbed_person_id   uuid references person(id),        -- null unless this
                                                              -- merge folded a
                                                              -- second, already-
                                                              -- resolved cluster
                                                              -- into the survivor
    moved_identity_ids   text[] not null,                    -- every identity id
                                                              -- whose person_id
                                                              -- changed to
                                                              -- survivor_person_id
                                                              -- as a result of
                                                              -- this merge
    prev_primary_name    text not null,                      -- survivor's name
                                                              -- before this merge's
                                                              -- naming recompute
    prev_preferred_name  text,
    reversed_at          timestamptz                         -- null until undone
);

create index on merge_log (survivor_person_id);
