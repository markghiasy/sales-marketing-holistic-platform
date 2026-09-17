"""Backend for the triage inbox's contact info panel — view a contact's
name and every known handle, edit the name, search for another identity
to link, or add a brand-new handle for a person who hasn't messaged yet.
See docs/superpowers/specs/2026-09-18-manual-hide-and-contact-editor-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass


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


def get_contact_info(cur, person_key: str) -> ContactInfo | None:
    cur.execute(
        """
        select id, channel, handle, display_name
        from identity
        where coalesce(person_id, id) = %s
        order by channel, handle
        """,
        (person_key,),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    name = next((r[3] for r in rows if r[3]), None) or "(unknown)"
    handles = [ContactHandle(identity_id=str(r[0]), channel=r[1], handle=r[2]) for r in rows]
    return ContactInfo(person_key=person_key, name=name, handles=handles)


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
        (f"%{query}%", exclude_person_key),
    )
    return [
        SearchResult(identity_id=str(r[0]), channel=r[1], handle=r[2], display_name=r[3])
        for r in cur.fetchall()
    ]
