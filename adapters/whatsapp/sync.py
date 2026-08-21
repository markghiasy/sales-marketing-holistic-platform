"""WhatsApp adapter entrypoint — Python half. Reads the JSON-lines queue
that ingest.js (the Node/Baileys connection layer) writes, maps each line
to the shared envelope, and upserts into the store.

Run: python -m adapters.whatsapp.sync

`ingest.js` must already be running (or have run at least once) for
queue.jsonl / self_jid.txt to exist — see runbook for how to start it.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from ..envelope import Channel, Direction, Envelope
from ..store_writer import upsert

NODE_DIR = Path(__file__).parent / "node"
QUEUE_PATH = NODE_DIR / "queue.jsonl"
SELF_JID_PATH = NODE_DIR / "self_jid.txt"


def _claim_queue() -> Path | None:
    """Atomically rename queue.jsonl out of the way so ingest.js (which
    keeps running and appending in real time) never writes to the same
    file this process is reading — same idea as an in-flight log rotate.
    Returns None if there's nothing to process right now.
    """
    if not QUEUE_PATH.exists():
        return None
    claimed = NODE_DIR / f"queue.processing.{int(time.time())}.jsonl"
    os.rename(QUEUE_PATH, claimed)
    return claimed


def _parse_timestamp(ts) -> datetime:
    if not ts:
        return datetime.now(UTC)
    if isinstance(ts, dict):
        # a batch queued before ingest.js's Long-serialisation fix
        # (2026-08-21) — {"low": <epoch seconds>, "high": 0, ...}. `high`
        # would matter for timestamps past year ~2106; not a real concern
        # here, so `low` alone is fine.
        ts = ts.get("low", 0)
    return datetime.fromtimestamp(int(ts), tz=UTC)


def _to_envelope(record: dict, self_jid: str) -> Envelope | None:
    text = record.get("text")
    remote_jid = record.get("remote_jid")
    msg_id = record.get("id")
    if not text or not remote_jid or not msg_id:
        return None

    from_me = bool(record.get("from_me"))
    is_group = bool(record.get("is_group"))
    direction = Direction.outbound if from_me else Direction.inbound

    if from_me:
        from_handle = self_jid
        # a group's JID is the *thread*, not a person — recording it as a
        # "to" participant would create a fake identity for the group
        # itself (found while self-reviewing: this had already happened —
        # 3 group JIDs existed as identity rows). Real fix needs the
        # group's actual member list (Baileys' groupMetadata(), a
        # separate async call not wired up yet) to record each member as
        # a participant; until then, a group message you sent gets no
        # "to" edges at all rather than one wrong one. Individual (1:1)
        # messages are unaffected.
        to_handles = [] if is_group else [remote_jid]
    else:
        # in a group, the participant field is the actual sender; in a 1:1
        # chat, remote_jid itself is the sender. Either way, "to" is just
        # you here — a group message's *other* recipients (everyone else
        # in the group) aren't captured, same missing-groupMetadata gap
        # as above.
        from_handle = record.get("participant") or remote_jid
        to_handles = [self_jid]

    sent_at = _parse_timestamp(record.get("timestamp"))

    return Envelope(
        channel=Channel.whatsapp,
        external_id=f"{remote_jid}:{msg_id}",
        thread_external_id=remote_jid,
        direction=direction,
        sent_at=sent_at,
        from_handle=from_handle,
        to_handles=to_handles,
        # push_name is WhatsApp's broadcast name for whoever sent the
        # message — only meaningful when they're the sender, not when we
        # are (from_me messages carry the recipient's jid, not their name)
        from_display_name=None if from_me else record.get("push_name"),
        subject=None,
        body_text=text,
        is_group=is_group,
        is_automated=False,
        raw=record,
    )


def run() -> None:
    load_dotenv()

    if not SELF_JID_PATH.exists():
        raise RuntimeError(
            f"no {SELF_JID_PATH} — ingest.js hasn't connected yet. "
            "Run `node ingest.js` in adapters/whatsapp/node/ first."
        )
    self_jid = SELF_JID_PATH.read_text().strip()

    claimed = _claim_queue()
    if claimed is None:
        print("nothing queued")
        return

    count = 0
    with (
        psycopg.connect(os.environ["DATABASE_URL"]) as conn,
        claimed.open(encoding="utf-8") as f,
    ):
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            env = _to_envelope(record, self_jid)
            if env is None:
                continue
            upsert(conn, env, self_jid)
            conn.commit()
            count += 1

    claimed.unlink()
    print(f"synced {count} messages")


if __name__ == "__main__":
    run()
