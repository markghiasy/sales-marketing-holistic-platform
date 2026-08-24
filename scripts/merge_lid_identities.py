"""One-off backfill: merge WhatsApp @lid identities into their real
phone-number identity.

Context: WhatsApp is mid-rollout of an opaque "@lid" identifier that
stands in for a contact's phone-number jid on some events. Before
ingest.js learned to resolve @lid -> phone number at ingest time, 11
contacts landed in the store as a second, unrelated identity keyed on
their @lid instead of their phone number. This reassigns their messages
to the identity already keyed on the phone number, backfills the display
name if only the @lid side had one, then removes the now-unreferenced
@lid identity row.

Input: adapters/whatsapp/node/lid_map.jsonl (one {"lid": ..., "pn": ...}
per line, produced by adapters/whatsapp/node/resolve_lids.js).

Run: python -m scripts.merge_lid_identities
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

LID_MAP_PATH = (
    Path(__file__).parent.parent / "adapters" / "whatsapp" / "node" / "lid_map.jsonl"
)


def merge(conn: psycopg.Connection, lid_handle: str, pn_handle: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "select id, display_name from identity where channel = 'whatsapp' and handle = %s",
            (lid_handle,),
        )
        lid_row = cur.fetchone()
        if lid_row is None:
            print(f"  {lid_handle}: no identity row — nothing to merge")
            return
        lid_id, lid_name = lid_row

        cur.execute(
            "select id, display_name from identity where channel = 'whatsapp' and handle = %s",
            (pn_handle,),
        )
        pn_row = cur.fetchone()
        if pn_row is None:
            # no messages have landed under the phone-jid form yet — the
            # @lid identity just becomes the canonical one, renamed
            cur.execute(
                "update identity set handle = %s where id = %s", (pn_handle, lid_id)
            )
            print(f"  {lid_handle} -> {pn_handle}: no phone identity existed, renamed in place")
            return
        pn_id, pn_name = pn_row

        if pn_name is None and lid_name is not None:
            cur.execute("update identity set display_name = %s where id = %s", (lid_name, pn_id))

        cur.execute(
            "update message set from_identity_id = %s where from_identity_id = %s",
            (pn_id, lid_id),
        )
        moved_messages = cur.rowcount

        # message_participant's PK is (message_id, identity_id, role) — a
        # row could already exist for pn_id on the same message (e.g. a
        # message that references both the person's lid and phone jid,
        # unlikely but not impossible), so re-point what we can and drop
        # whatever's left as an unresolvable duplicate rather than crash
        cur.execute(
            """
            update message_participant set identity_id = %s
            where identity_id = %s
              and not exists (
                  select 1 from message_participant mp2
                  where mp2.message_id = message_participant.message_id
                    and mp2.identity_id = %s
                    and mp2.role = message_participant.role
              )
            """,
            (pn_id, lid_id, pn_id),
        )
        moved_participants = cur.rowcount
        cur.execute("delete from message_participant where identity_id = %s", (lid_id,))
        cur.execute("delete from identity where id = %s", (lid_id,))

        print(
            f"  {lid_handle} -> {pn_handle}: merged "
            f"({moved_messages} messages, {moved_participants} participant rows)"
        )


def run() -> None:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL", "postgresql://comms:comms@localhost:5432/comms")

    mappings = []
    for line in LID_MAP_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("pn"):
            mappings.append((rec["lid"], rec["pn"]))

    print(f"{len(mappings)} lid->phone mappings to apply")
    with psycopg.connect(database_url) as conn:
        for lid_handle, pn_handle in mappings:
            merge(conn, lid_handle, pn_handle)
        conn.commit()


if __name__ == "__main__":
    run()
