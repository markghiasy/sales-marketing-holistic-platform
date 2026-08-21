"""One-off: apply names from contacts.jsonl (written by ingest.js's
contacts.upsert handler) onto existing WhatsApp identity rows. Separate
from sync.py because contacts and messages arrive on different Baileys
events with different lifecycles (contacts.upsert only fires once per
fresh pairing; messages queue continuously) — no reason to force them
through the same entrypoint.

Run: python -m adapters.whatsapp.apply_contacts
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

CONTACTS_PATH = Path(__file__).parent / "node" / "contacts.jsonl"


def run() -> None:
    load_dotenv()
    if not CONTACTS_PATH.exists():
        print("no contacts.jsonl — nothing to apply")  # noqa: T201
        return

    updated = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur, CONTACTS_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                c = json.loads(line)
                name = c.get("name") or c.get("notify")
                if not name:
                    continue
                cur.execute(
                    """
                    update identity
                    set display_name = %s
                    where channel = 'whatsapp' and handle = %s and display_name is null
                    """,
                    (name, c["jid"]),
                )
                updated += cur.rowcount
        conn.commit()

    print(f"updated {updated} identity rows")  # noqa: T201


if __name__ == "__main__":
    run()
