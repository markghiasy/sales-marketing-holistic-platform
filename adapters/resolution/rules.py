# adapters/resolution/rules.py
"""Rules 1 & 3 of §8's identity-resolution ladder — exact email match
and the contact bridge. §8's Rule 2 (exact phone match) is folded into
Rule 3 here rather than implemented separately: a phone-only match with
no corroborating email has no second identity to merge into on its own
(graph_contact isn't itself an identity), and is weaker evidence than
the other automatic rules anyway — decided with Eva 2026-09-03, see
Task 6's header note. Both rules here are "automatic": they write an
already-confirmed link_candidate row (not a bare identity.person_id
write — see the design doc's "Evidence provenance" section for why),
subject to the safety checks in safety.py. See
docs/superpowers/specs/2026-09-03-identity-resolution-design.md.
"""

from __future__ import annotations

import re

from adapters.outlook.contacts_sync import _normalise_phone

from .merge import apply_merge
from .safety import (
    MAX_CLUSTER_SIZE,
    cluster_names_contradict,
    cluster_size_after_merge,
    has_existing_candidate,
    is_generic_role_email,
)


def _whatsapp_phone_digits(handle: str) -> str | None:
    """Extracts the digit portion of a WhatsApp identity.handle (a raw
    JID like '15806709090@s.whatsapp.net'), or None for a group chat
    ('...@g.us') or anything not shaped like a person's number."""
    if handle.endswith("@g.us"):
        return None
    if "@" not in handle:
        return None
    digits = handle.split("@", 1)[0]
    return digits if digits.isdigit() else None


def _propose_and_maybe_confirm(
    cur, identity_a_id: str, identity_b_id: str, method: str, reason: str, blocked_reason: str | None
) -> bool:
    """Writes one link_candidate row for the pair. If blocked_reason is
    given, or a safety check fails, status is 'pending' and no merge is
    applied. Otherwise status is 'confirmed' and the merge is applied
    immediately. Returns True if a row was written (it always is, unless
    a rejected candidate for this pair already exists, in which case
    nothing is written and this returns False)."""
    if has_existing_candidate(cur, identity_a_id, identity_b_id):
        return False

    full_reason = reason
    status = "confirmed"

    if blocked_reason:
        status = "pending"
        full_reason = f"{reason} — {blocked_reason}"
    elif cluster_names_contradict(cur, identity_a_id, identity_b_id):
        status = "pending"
        full_reason = f"{reason} — contradicting display names, needs review"
    elif cluster_size_after_merge(cur, identity_a_id, identity_b_id) > MAX_CLUSTER_SIZE:
        status = "pending"
        full_reason = f"{reason} — merge would create an implausibly large cluster, needs review"

    cur.execute(
        """
        insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason)
        values (%s, %s, 1.0, %s, %s, %s)
        """,
        (identity_a_id, identity_b_id, method, status, full_reason),
    )

    if status == "confirmed":
        apply_merge(cur, identity_a_id, identity_b_id)

    return True


def rule_exact_email_match(cur) -> int:
    cur.execute(
        """
        select i.id, i.handle, lc.id, lc.email, lc.first_name, lc.last_name
        from identity i
        join linkedin_connection lc on lower(lc.email) = i.handle
        where i.channel = 'outlook' and lc.email is not null and lc.email != ''
        """
    )
    rows = cur.fetchall()
    count = 0
    for outlook_identity_id, email, connection_id, _, first_name, last_name in rows:
        # display_name must come from the LinkedIn connection's name here —
        # without it, the newly-created linkedin identity always has a NULL
        # display_name, which silently disables the names_contradict safety
        # check below for every Rule 1 match (found while hand-tracing this
        # rule against its own test before dispatch — a real defect, not
        # just a test gap)
        linkedin_display_name = f"{first_name or ''} {last_name or ''}".strip() or None
        cur.execute(
            """
            insert into identity (channel, handle, display_name) values ('linkedin', %s, %s)
            on conflict (channel, handle) do update
                set display_name = coalesce(identity.display_name, excluded.display_name)
            returning id
            """,
            (connection_id, linkedin_display_name),
        )
        # the on conflict clause has no WHERE, so it always fires and
        # RETURNING always yields a row — no separate SELECT needed, even
        # when the update is a same-value no-op
        linkedin_identity_id = str(cur.fetchone()[0])

        blocked_reason = (
            f"generic role address {email} — not merged automatically"
            if is_generic_role_email(email)
            else None
        )
        reason = f"exact email match on {email}"
        if _propose_and_maybe_confirm(
            cur, str(outlook_identity_id), linkedin_identity_id, "exact_email", reason, blocked_reason
        ):
            count += 1
    return count


def rule_contact_bridge(cur) -> int:
    cur.execute("select id, emails, phones, display_name from graph_contact")
    contacts = cur.fetchall()

    # both identity tables are small relative to graph_contact and don't
    # change mid-run, so load each once instead of re-querying per contact
    # (or, for whatsapp, per digit-candidate) — this was the dominant cost
    # of a real run against the hosted database, one network round trip
    # per lookup instead of two queries total
    cur.execute("select handle, id from identity where channel = 'outlook'")
    outlook_by_handle = {handle: str(identity_id) for handle, identity_id in cur.fetchall()}

    cur.execute("select id, handle from identity where channel = 'whatsapp'")
    whatsapp_by_digits: dict[str, str] = {}
    for wa_id, handle in cur.fetchall():
        digits = _whatsapp_phone_digits(handle)
        if digits:
            whatsapp_by_digits.setdefault(digits, str(wa_id))

    count = 0
    for _contact_id, emails, phones, contact_display_name in contacts:
        if not emails or not phones:
            continue
        outlook_identity_id = None
        matched_email = None
        for email in emails:
            candidate = outlook_by_handle.get(email.lower())
            if candidate:
                outlook_identity_id = candidate
                matched_email = email
                break
        if outlook_identity_id is None:
            continue

        whatsapp_identity_id = None
        for phone in phones:
            candidate = whatsapp_by_digits.get(phone)
            if candidate:
                whatsapp_identity_id = candidate
                break
        if whatsapp_identity_id is None:
            continue

        blocked_reason = (
            f"generic role address {matched_email} — not merged automatically"
            if is_generic_role_email(matched_email)
            else None
        )
        reason = f"contact record {contact_display_name or '(no name)'} links this email and phone"
        if _propose_and_maybe_confirm(
            cur, outlook_identity_id, whatsapp_identity_id, "contact_bridge", reason, blocked_reason
        ):
            count += 1
    return count


_SIGNATURE_LINES = 6  # how many trailing lines of body_text count as
                       # "the signature block" for phone scanning
_PHONE_CANDIDATE_RE = re.compile(r"[\d][\d\s().-]{6,}\d")


def _extract_signature_phone_digits(body_text: str) -> list[str]:
    lines = [line for line in body_text.strip().splitlines() if line.strip()]
    signature_region = "\n".join(lines[-_SIGNATURE_LINES:])
    candidates = []
    for match in _PHONE_CANDIDATE_RE.finditer(signature_region):
        digits = _normalise_phone(match.group())
        if len(digits) >= 7:  # shorter than this isn't a plausible phone number
            candidates.append(digits)
    return candidates


def rule_signature_phone(cur) -> int:
    # both directions are scanned: a phone number in the SIGNER's own
    # signature is equally valid evidence whether they sent us the message
    # (outbound) or we received it from them (inbound) — from_identity_id
    # is always whoever wrote the message, so the link target is correct
    # either way.
    cur.execute(
        """
        select id, from_identity_id, body_text
        from message
        where channel = 'outlook'
        """
    )
    messages = cur.fetchall()

    # loaded once, not once per digit-candidate: with thousands of real
    # messages, re-running this query per candidate was the dominant cost
    # of a real run against the hosted database (one network round trip
    # per digit found, on top of one per message)
    #
    # is_self=true rows excluded — real bug found 2026-09-09 against the
    # hosted database: an automated confirmation email (a visitor sign-in
    # system) echoed the mailbox owner's own submitted phone number back
    # in its body ("Your Details: <name>, <email>, <phone>"), which this
    # rule then read as the confirmation sender's own signature phone,
    # producing false candidates linking real senders (a visitor-
    # management system, several other automated senders) to the owner's
    # own WhatsApp identity. This rule exists to link OTHER people's
    # Outlook and WhatsApp identities — it should never be able to
    # produce "the owner, linked to themselves" as a side effect of
    # whatever number happens to appear in a message body, regardless of
    # whose signature it actually came from.
    cur.execute("select id, handle from identity where channel = 'whatsapp' and is_self = false")
    whatsapp_by_digits: dict[str, str] = {}
    for wa_id, handle in cur.fetchall():
        digits = _whatsapp_phone_digits(handle)
        if digits:
            whatsapp_by_digits.setdefault(digits, str(wa_id))

    count = 0
    for message_id, from_identity_id, body_text in messages:
        if from_identity_id is None or not body_text:
            continue
        for digits in _extract_signature_phone_digits(body_text):
            wa_id = whatsapp_by_digits.get(digits)
            if wa_id is None:
                continue
            if has_existing_candidate(cur, str(from_identity_id), wa_id):
                continue
            reason = f"phone {digits} found in signature of message {message_id}, matches WhatsApp handle {digits}"
            cur.execute(
                """
                insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason)
                values (%s, %s, 0.8, 'email_signature_phone', 'pending', %s)
                """,
                (str(from_identity_id), wa_id, reason),
            )
            count += 1
    return count
