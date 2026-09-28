-- Withdrawal is not a human rejection. Preserve source, score and original reason.
-- Confirmed/rejected history is unchanged; no person or identity is unmerged.
update link_candidate
set status = 'retired',
    reason = concat_ws(E'\n', reason,
        'Rule retired 2026-09-28: same-channel LinkedIn name-only evidence is insufficient for review.')
where method = 'linkedin_same_channel_dedupe' and status = 'pending';
