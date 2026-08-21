-- Network graph, v1 (build plan §10) — "the graph is a view over the
-- store, not a separate system." No new tables: message_participant
-- already is the edge data (§7 "Four choices worth defending"); this is
-- just SQL that reads it.
--
-- Ego-network, not general social graph: every row is "this contact's
-- relationship with me" (matches §12's use — scoring the principal's own
-- network), not relationships between two arbitrary third parties.
--
-- Resolution-ready on purpose: groups by coalesce(identity.person_id,
-- identity.id), so today (§8 hasn't run — person_id is null on
-- everything) this behaves as one row per identity/handle, and once
-- resolution starts filling in person_id for confident matches, the same
-- view starts merging rows automatically. No rewrite needed later.

create view contact_stats as
select
    coalesce(i.person_id, i.id) as contact_key,
    max(i.display_name)         as display_name,
    array_agg(distinct i.channel) as channels,
    array_agg(distinct i.handle)  as handles,
    count(*) filter (where m.direction = 'outbound') as sent_count,
    count(*) filter (where m.direction = 'inbound')  as received_count,
    count(*)                                          as total_count,
    min(m.sent_at) as first_contact_at,
    max(m.sent_at) as last_contact_at
from identity i
join message_participant mp on mp.identity_id = i.id
join message m on m.id = mp.message_id
where i.is_self = false
group by coalesce(i.person_id, i.id);

-- Reciprocity (§10: "the one people skip and the most informative") as
-- its own view rather than baked into contact_stats — keeps the raw
-- counts above simple to read/debug on their own, per §12's
-- "score_rationale is a first-class field, not a debug log" spirit:
-- anyone should be able to see the inputs, not just the output.
create view contact_reciprocity as
select
    contact_key,
    case
        when greatest(sent_count, received_count) = 0 then null
        else least(sent_count, received_count)::real
             / greatest(sent_count, received_count)::real
    end as reciprocity_ratio
from contact_stats;

-- The most recent message with each contact, for the "context" input
-- (§10) and the relationship_context §7 wants on the outreach table
-- later — "last touch, channel, warmth," not just a number.
create view contact_last_message as
select distinct on (coalesce(i.person_id, i.id))
    coalesce(i.person_id, i.id) as contact_key,
    m.channel,
    m.sent_at,
    m.direction,
    left(m.body_text, 280) as snippet
from identity i
join message_participant mp on mp.identity_id = i.id
join message m on m.id = mp.message_id
where i.is_self = false
order by coalesce(i.person_id, i.id), m.sent_at desc;

-- Placeholder graph-strength formula — brief §10 names the four inputs
-- (recency, frequency, reciprocity, context) but doesn't specify how to
-- combine them into one score. This weighting is a first guess, not a
-- calibrated one: recency decays over 90 days, frequency and reciprocity
-- are weighted equally. Needs revisiting once there's enough real
-- relationship data to sanity-check against — "does this ranking match
-- who I'd actually say I'm close to" (§14's own checkpoint language).
create view contact_graph_strength as
select
    s.contact_key,
    s.display_name,
    s.channels,
    s.total_count,
    r.reciprocity_ratio,
    s.last_contact_at,
    greatest(
        0.0,
        1.0 - extract(epoch from (now() - s.last_contact_at)) / (90 * 86400)
    ) as recency_score,
    least(1.0, s.total_count / 20.0) as frequency_score,
    coalesce(r.reciprocity_ratio, 0.0) as reciprocity_score,
    (
        0.4 * greatest(0.0, 1.0 - extract(epoch from (now() - s.last_contact_at)) / (90 * 86400))
        + 0.3 * least(1.0, s.total_count / 20.0)
        + 0.3 * coalesce(r.reciprocity_ratio, 0.0)
    ) as graph_strength
from contact_stats s
left join contact_reciprocity r on r.contact_key = s.contact_key
order by graph_strength desc;
