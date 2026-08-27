"""Contacts ingest entrypoint (§8's bridge source, Block A scope per §14).
Pulls the whole /me/contacts folder and upserts into graph_contact — no
matching/linking logic here, that's Block B's resolution v1.

Probed against this real mailbox (2026-08-27): both /me/contacts and
/me/people returned 0 results. Expect this to sync 0 contacts until a
mailbox that actually has saved contacts gets connected — that's the
mailbox's own state, not a bug in this script.

Run: python -m adapters.outlook.contacts_sync
"""

from __future__ import annotations

import os
import re

import psycopg
from dotenv import load_dotenv

from .client import fetch_contacts

_DIGITS_RE = re.compile(r"\D")


def _normalise_phone(raw: str) -> str:
    # digits only, no leading '+' — matches the numeric part of a
    # WhatsApp jid (e.g. "15806709090@s.whatsapp.net"), not full E.164.
    # Deliberately the same normalisation the bridge (Block B) will need
    # to compare against identity.handle for whatsapp — decided here so
    # there's one place this rule lives, not reinvented at match time.
    return _DIGITS_RE.sub("", raw)


def _to_row(raw: dict) -> tuple[str, str | None, list[str], list[str]]:
    contact_id = raw["id"]
    display_name = raw.get("displayName") or None
    emails = [
        e["address"].lower()
        for e in raw.get("emailAddresses", [])
        if e.get("address")
    ]
    phone_fields = (
        [raw.get("mobilePhone")]
        + raw.get("businessPhones", [])
        + raw.get("homePhones", [])
    )
    phones = [_normalise_phone(p) for p in phone_fields if p]
    return contact_id, display_name, emails, phones


def run() -> None:
    load_dotenv()
    count = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for raw in fetch_contacts():
            contact_id, display_name, emails, phones = _to_row(raw)
            cur.execute(
                """
                insert into graph_contact (id, display_name, emails, phones, synced_at)
                values (%s, %s, %s, %s, now())
                on conflict (id) do update
                    set display_name = excluded.display_name,
                        emails = excluded.emails,
                        phones = excluded.phones,
                        synced_at = excluded.synced_at
                """,
                (contact_id, display_name, emails, phones),
            )
            count += 1
        conn.commit()
    print(f"synced {count} contacts")


if __name__ == "__main__":
    run()
