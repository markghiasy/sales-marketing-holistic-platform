"""One-off: backfills is_automated on Outlook messages already in the
store. Two independent passes, each safe to run alone or together:

1. **Local pass** (no network/auth needed): recomputes
   List-Unsubscribe/sender-pattern/sender-domain (§9 tier 1, added
   2026-09-09 — see adapters/outlook/sync.py's is_automated()) from each
   row's already-stored `raw` payload. Every row already has
   internetMessageHeaders in `raw` (confirmed against real data), so
   this needs nothing beyond the local database.
2. **Classification pass** (needs a live Graph token): backfills Graph's
   own Focused/Other classification for messages ingested before
   adapters/outlook/client.py started selecting inferenceClassification
   (2026-08-28) — that field is missing from every existing row's `raw`
   entirely (confirmed against real data), so this signal can only be
   recovered by re-fetching from Graph, not from stored data.

Both passes OR their result into the existing is_automated value rather
than overwriting — running one pass never undoes what the other found.
store_writer's upsert is on-conflict-do-nothing, so a normal re-sync
never touches existing rows; this script is the only way to bring
already-ingested messages in line with is_automated logic that didn't
exist yet when they were first ingested.

Run the local pass (default, no auth needed):
    python scripts/backfill_outlook_automated.py

Also run the classification pass (needs a live Outlook auth session):
    python scripts/backfill_outlook_automated.py --with-classification

Safe to re-run — every row it touches gets the same correct value either way.
"""

from __future__ import annotations

import os
import sys

import psycopg
from dotenv import load_dotenv

from adapters.outlook.client import GRAPH_BASE, _get_with_retry, get_access_token
from adapters.outlook.sync import is_automated as _compute_is_automated


def _run_local_pass(conn: psycopg.Connection) -> int:
    """Recomputes is_automated from each row's stored raw payload — no
    network needed. Returns the number of rows updated."""
    cur = conn.cursor()
    cur.execute(
        """
        select m.id, m.raw, m.is_automated, i.handle
        from message m
        join identity i on i.id = m.from_identity_id
        where m.channel = 'outlook'
        """
    )
    rows = cur.fetchall()

    updated = 0
    for message_id, raw, current_is_automated, from_handle in rows:
        recomputed = _compute_is_automated(raw, from_handle)
        new_value = current_is_automated or recomputed
        if new_value != current_is_automated:
            cur.execute(
                "update message set is_automated = %s where id = %s",
                (new_value, message_id),
            )
            updated += 1
    conn.commit()
    print(f"local pass: checked {len(rows)} messages, updated {updated} rows")
    return updated


def _fetch_classifications(folder: str, headers: dict) -> dict[str, bool]:
    """Returns {internetMessageId: is_automated} for every message in
    the given folder, via plain pagination (no delta needed — this runs
    once)."""
    out: dict[str, bool] = {}
    url = (
        f"{GRAPH_BASE}/me/mailFolders/{folder}/messages"
        f"?$top=50&$select=internetMessageId,inferenceClassification"
    )
    while url:
        resp = _get_with_retry(url, headers)
        data = resp.json()
        for msg in data.get("value", []):
            msg_id = msg.get("internetMessageId")
            if msg_id is None:
                continue
            out[msg_id] = msg.get("inferenceClassification") == "other"
        url = data.get("@odata.nextLink")
    return out


def _run_classification_pass(conn: psycopg.Connection) -> int:
    """Re-fetches Graph's own classification for messages whose raw
    payload predates that field. Returns the number of rows updated."""
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    classifications: dict[str, bool] = {}
    for folder in ("inbox", "sentitems"):
        classifications.update(_fetch_classifications(folder, headers))

    cur = conn.cursor()
    updated = 0
    for msg_id, classification_is_automated in classifications.items():
        cur.execute(
            """
            update message set is_automated = (is_automated or %s)
            where channel = 'outlook' and external_id = %s and is_automated != (is_automated or %s)
            """,
            (classification_is_automated, msg_id, classification_is_automated),
        )
        updated += cur.rowcount
    conn.commit()
    print(f"classification pass: checked {len(classifications)} messages, updated {updated} rows")
    return updated


def run(with_classification: bool = False) -> None:
    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        _run_local_pass(conn)
        if with_classification:
            _run_classification_pass(conn)


if __name__ == "__main__":
    run(with_classification="--with-classification" in sys.argv)
