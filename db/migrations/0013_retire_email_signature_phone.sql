-- db/migrations/0013_retire_email_signature_phone.sql
-- Retires rule_signature_phone, on the owner's ruling 2026-09-30.
--
-- Two independent measurements agree the rule is wrong more often than it
-- is right: 2/9 (finding 21, 15 Sep) and 33.3% precision with 40% of pairs
-- unjudgeable (28 Sep blind adjudication, n=10). The mechanism is
-- understood, not merely observed: a phone number in a QUOTED signature
-- block belongs to whoever was quoted, not to the sender of the message it
-- was found in, so the rule pairs the wrong person with that WhatsApp
-- handle. Widening the mailbox scope (finding 14) made it worse, not
-- better — more quoted signatures produced 57 more bad candidates.
--
-- Same shape as 0012: withdrawal is not a human rejection. The original
-- evidence, score and reason are preserved; confirmed/rejected history is
-- untouched; no person or identity is unmerged.
update link_candidate
set status = 'retired',
    reason = concat_ws(E'\n', reason,
        'Rule retired 2026-09-30: a phone in a quoted signature belongs to the quoted party, '
        'not the sender. Measured 2/9 and 33.3% across two independent adjudications.')
where method = 'email_signature_phone' and status = 'pending';
