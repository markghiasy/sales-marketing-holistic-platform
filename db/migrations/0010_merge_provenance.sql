-- Record the rule and decision path for every merge without guessing old provenance.
alter table merge_log add column method text;
alter table merge_log add column decision_kind text;
update merge_log set method = 'unknown_legacy', decision_kind = 'unknown_legacy';
alter table merge_log alter column method set not null;
alter table merge_log alter column decision_kind set not null;
alter table merge_log add constraint merge_log_method_nonempty check (length(trim(method)) > 0);
alter table merge_log add constraint merge_log_decision_kind_valid
    check (decision_kind in ('automatic', 'review', 'manual', 'unknown_legacy'));
-- Intentionally no defaults: a new caller must supply attribution explicitly.
create index on merge_log (method, decision_kind);
