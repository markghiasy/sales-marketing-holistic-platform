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

from .merge import apply_merge
from .safety import (
    MAX_CLUSTER_SIZE,
    cluster_size_after_merge,
    has_existing_rejected_candidate,
    is_generic_role_email,
    names_contradict,
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
    if has_existing_rejected_candidate(cur, identity_a_id, identity_b_id):
        return False

    full_reason = reason
    status = "confirmed"

    if blocked_reason:
        status = "pending"
        full_reason = f"{reason} — {blocked_reason}"
    elif names_contradict(*_display_names(cur, identity_a_id, identity_b_id)):
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


def _display_names(cur, identity_a_id: str, identity_b_id: str) -> tuple[str | None, str | None]:
    cur.execute("select display_name from identity where id = %s", (identity_a_id,))
    name_a = cur.fetchone()[0]
    cur.execute("select display_name from identity where id = %s", (identity_b_id,))
    name_b = cur.fetchone()[0]
    return name_a, name_b


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
            "insert into identity (channel, handle, display_name) values ('linkedin', %s, %s) on conflict (channel, handle) do nothing",
            (connection_id, linkedin_display_name),
        )
        cur.execute(
            "select id from identity where channel = 'linkedin' and handle = %s", (connection_id,)
        )
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
    count = 0
    for _contact_id, emails, phones, contact_display_name in contacts:
        if not emails or not phones:
            continue
        outlook_identity_id = None
        for email in emails:
            cur.execute(
                "select id from identity where channel = 'outlook' and handle = %s", (email.lower(),)
            )
            row = cur.fetchone()
            if row:
                outlook_identity_id = str(row[0])
                break
        if outlook_identity_id is None:
            continue

        whatsapp_identity_id = None
        cur.execute("select id, handle from identity where channel = 'whatsapp'")
        for wa_id, handle in cur.fetchall():
            digits = _whatsapp_phone_digits(handle)
            if digits and digits in phones:
                whatsapp_identity_id = str(wa_id)
                break
        if whatsapp_identity_id is None:
            continue

        reason = f"contact record {contact_display_name or '(no name)'} links this email and phone"
        if _propose_and_maybe_confirm(
            cur, outlook_identity_id, whatsapp_identity_id, "contact_bridge", reason, None
        ):
            count += 1
    return count
