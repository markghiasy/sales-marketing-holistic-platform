"""One-off: backfills is_automated on Outlook messages already in the
store from before adapters/outlook/client.py started selecting
inferenceClassification (2026-08-28). Every message already ingested has
is_automated=False regardless of its real classification, since the
field didn't exist in the raw payload at ingest time — store_writer's
upsert is on-conflict-do-nothing, so a normal re-sync never touches
existing rows. This re-fetches just id + inferenceClassification (a
light, id-only listing, not a full message refetch) and updates
matching rows by internetMessageId.

Run once: python scripts/backfill_outlook_automated.py
Safe to re-run — every row it touches gets the same correct value either way.
"""

from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv

from adapters.outlook.client import GRAPH_BASE, _get_with_retry, get_access_token


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


def run() -> None:
    load_dotenv()
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    classifications: dict[str, bool] = {}
    for folder in ("inbox", "sentitems"):
        classifications.update(_fetch_classifications(folder, headers))

    updated = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for msg_id, is_automated in classifications.items():
            cur.execute(
                """
                update message set is_automated = %s
                where channel = 'outlook' and external_id = %s and is_automated != %s
                """,
                (is_automated, msg_id, is_automated),
            )
            updated += cur.rowcount
        conn.commit()

    print(f"checked {len(classifications)} messages, updated {updated} rows")


if __name__ == "__main__":
    run()
