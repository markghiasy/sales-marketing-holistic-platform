-- db/migrations/0008_contact_last_message_is_automated.sql
-- Adds message.is_automated to contact_last_message (0002_graph_views.sql)
-- so the triage inbox can hide contacts whose most recent message was
-- flagged by the noise parser (§9 tier 1) — built earlier this session
-- but never actually wired into the inbox list until now. Confirmed
-- 2026-09-17 against real data: 3006 of 4809 real Outlook messages
-- (62.5%) are_automated=true, none of it filtered anywhere.

create or replace view contact_last_message as
select distinct on (coalesce(i.person_id, i.id))
    coalesce(i.person_id, i.id) as contact_key,
    m.channel,
    m.sent_at,
    m.direction,
    left(m.body_text, 280) as snippet,
    m.is_automated
from identity i
join message_participant mp on mp.identity_id = i.id
join message m on m.id = mp.message_id
where i.is_self = false
order by coalesce(i.person_id, i.id), m.sent_at desc;
