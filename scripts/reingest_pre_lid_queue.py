"""One-off: replay adapters/whatsapp/node/queue.pre_lid_fix.jsonl (the
backlog captured before ingest.js learned to resolve @lid identifiers)
through the normal WhatsApp sync path, substituting each @lid for its
resolved phone-number jid first.

Distinct from scripts/merge_lid_identities.py: that one fixes identities
already in the store; this one gets the messages that were still sitting
in the queue, never synced at all, into the store in the first place —
correctly, on the way in, instead of needing another merge pass after.

Run: python -m scripts.reingest_pre_lid_queue
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from adapters.store_writer import upsert
from adapters.whatsapp.sync import _to_envelope

NODE_DIR = Path(__file__).parent.parent / "adapters" / "whatsapp" / "node"
QUEUE_PATH = NODE_DIR / "queue.pre_lid_fix.jsonl"
LID_MAP_PATH = NODE_DIR / "lid_map.jsonl"
SELF_JID_PATH = NODE_DIR / "self_jid.txt"


def _load_lid_map() -> dict[str, str]:
    mapping = {}
    for line in LID_MAP_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("pn"):
            mapping[rec["lid"]] = rec["pn"]
    return mapping


def run() -> None:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL", "postgresql://comms:comms@localhost:5432/comms")
    self_jid = SELF_JID_PATH.read_text().strip()
    lid_map = _load_lid_map()

    count = 0
    skipped = 0
    with (
        psycopg.connect(database_url) as conn,
        QUEUE_PATH.open(encoding="utf-8") as f,
    ):
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("remote_jid") in lid_map:
                record["remote_jid"] = lid_map[record["remote_jid"]]
            if record.get("participant") in lid_map:
                record["participant"] = lid_map[record["participant"]]

            env = _to_envelope(record, self_jid)
            if env is None:
                skipped += 1
                continue
            upsert(conn, env, self_jid)
            count += 1
        conn.commit()

    print(f"reingested {count} messages ({skipped} skipped — no text/id), lid map had {len(lid_map)} entries")


if __name__ == "__main__":
    run()
