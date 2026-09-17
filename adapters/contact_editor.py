"""Backend for the triage inbox's contact info panel — view a contact's
name and every known handle, edit the name, search for another identity
to link, or add a brand-new handle for a person who hasn't messaged yet.
See docs/superpowers/specs/2026-09-18-manual-hide-and-contact-editor-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .resolution.merge import apply_merge


@dataclass
class ContactHandle:
    identity_id: str
    channel: str
    handle: str


@dataclass
class ContactInfo:
    person_key: str
    name: str
    handles: list[ContactHandle]


def _resolve_contact_key(cur, person_key: str) -> str:
    """A person_key can go stale after apply_merge() assigns a brand-new
    person id to an identity whose own id was captured as the key before
    it had one — see docs/superpowers/plans/2026-09-18-manual-hide-and-
    contact-editor.md Task 7. Resolves through identity.id first (picking
    up whatever person_id that specific identity has now), falling back
    to treating person_key as a literal person id when no identity has
    that id (the pre-existing, still-correct behavior for an actual
    person id)."""
    cur.execute("select coalesce(person_id, id) from identity where id = %s", (person_key,))
    row = cur.fetchone()
    return str(row[0]) if row is not None else person_key


def get_contact_info(cur, person_key: str) -> ContactInfo | None:
    # person_key may be a bare identity's own id (still unresolved, i.e.
    # what get_contact_info always accepted) OR that same identity's id
    # after it has since been resolved into a person elsewhere (link_contact
    # / add_contact_handle create a *new* person row with its own random
    # id — see apply_merge — so the identity's original id no longer
    # equals coalesce(person_id, id) once resolved). Resolve through
    # identity.id first so a caller holding an identity's own id from
    # before resolution still finds the contact; falls back to treating
    # person_key as a person id directly, as before.
    effective_key = _resolve_contact_key(cur, person_key)

    cur.execute(
        """
        select id, channel, handle, display_name
        from identity
        where coalesce(person_id, id) = %s
        order by channel, handle
        """,
        (effective_key,),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    name = next((r[3] for r in rows if r[3]), None) or "(unknown)"
    handles = [ContactHandle(identity_id=str(r[0]), channel=r[1], handle=r[2]) for r in rows]
    return ContactInfo(person_key=effective_key, name=name, handles=handles)


@dataclass
class SearchResult:
    identity_id: str
    channel: str
    handle: str
    display_name: str | None


def search_identities(cur, query: str, exclude_person_key: str) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []
    effective_exclude_key = _resolve_contact_key(cur, exclude_person_key)
    cur.execute(
        """
        select id, channel, handle, display_name
        from identity
        where is_self = false
          and handle ilike %s
          and coalesce(person_id, id) != %s
        order by handle
        limit 10
        """,
        (f"%{query}%", effective_exclude_key),
    )
    return [
        SearchResult(identity_id=str(r[0]), channel=r[1], handle=r[2], display_name=r[3])
        for r in cur.fetchall()
    ]


def update_contact_name(cur, person_key: str, name: str) -> None:
    effective_key = _resolve_contact_key(cur, person_key)
    cur.execute(
        "update identity set display_name = %s where coalesce(person_id, id) = %s",
        (name, effective_key),
    )


def link_contact(cur, person_key: str, other_identity_id: str) -> str:
    old_contact_key = _resolve_contact_key(cur, person_key)
    cur.execute(
        "select id from identity where coalesce(person_id, id) = %s limit 1",
        (old_contact_key,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no identity found for person_key {person_key}")
    representative_id = str(row[0])
    new_contact_key = apply_merge(cur, representative_id, other_identity_id)

    # #10: if the pre-merge contact_key had a contact_hidden row (this
    # contact was manually hidden), the merge can move it to a different
    # (brand-new) resolved key — see apply_merge — leaving the old
    # contact_hidden row orphaned and the hide silently stopping. Move it
    # forward to the new key rather than leaving it stranded.
    cur.execute(
        "update contact_hidden set contact_key = %s where contact_key = %s and %s != %s",
        (new_contact_key, old_contact_key, new_contact_key, old_contact_key),
    )

    return new_contact_key


_WHATSAPP_SUFFIX = "@s.whatsapp.net"


def _guess_channel_and_handle(raw_input: str) -> tuple[str, str]:
    text = raw_input.strip()
    if "@" in text:
        return "outlook", text.lower()
    digits_only = re.sub(r"[^\d]", "", text)
    non_digit_chars = set(text) - set("0123456789+()- ")
    if digits_only and len(digits_only) >= 7 and not non_digit_chars:
        return "whatsapp", f"{digits_only}{_WHATSAPP_SUFFIX}"
    return "outlook", text.lower()


def add_contact_handle(cur, person_key: str, raw_handle: str) -> str:
    effective_key = _resolve_contact_key(cur, person_key)
    channel, handle = _guess_channel_and_handle(raw_handle)

    cur.execute("select id from identity where channel = %s and handle = %s", (channel, handle))
    if cur.fetchone() is not None:
        raise ValueError(f"identity already exists for {channel}:{handle}")

    cur.execute(
        "select person_id, id from identity where coalesce(person_id, id) = %s limit 1",
        (effective_key,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no identity found for person_key {person_key}")
    person_id, representative_id = row

    if person_id is None:
        cur.execute("select display_name from identity where id = %s", (representative_id,))
        (existing_name,) = cur.fetchone()
        cur.execute(
            "insert into person (primary_name) values (%s) returning id",
            (existing_name or "",),
        )
        person_id = cur.fetchone()[0]
        cur.execute("update identity set person_id = %s where id = %s", (person_id, representative_id))

    cur.execute(
        "insert into identity (channel, handle, person_id) values (%s, %s, %s) returning id",
        (channel, handle, person_id),
    )
    return str(cur.fetchone()[0])
