"""Outlook adapter entrypoint: pull from Graph, normalise to the envelope,
upsert into the store. Full backfill on first run, delta thereafter.

Run: python -m adapters.outlook.sync
"""

from __future__ import annotations

import html
import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from .client import fetch_messages
from ..envelope import Channel, Direction, Envelope
from ..store_writer import upsert

DELTA_LINK_PATH = Path(__file__).parent / ".delta_link.txt"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(body: dict) -> str:
    """Graph returns body as {contentType, content}. Plain-text it, no
    quoted-reply-chain stripping yet — noted as follow-up in the runbook."""
    content = body.get("content", "") or ""
    if body.get("contentType") == "html":
        content = _TAG_RE.sub(" ", content)
        content = html.unescape(content)
    return content.strip()


def _to_envelope(raw: dict, self_handles: set[str]) -> Envelope | None:
    if raw.get("internetMessageId") is None:
        return None  # can't guarantee idempotency without it — drop, don't guess

    from_addr = raw.get("from", {}).get("emailAddress", {})
    from_handle = (from_addr.get("address") or "").lower()
    to_addrs = [r.get("emailAddress", {}) for r in raw.get("toRecipients", [])]
    to_handles = [(a.get("address") or "").lower() for a in to_addrs]

    direction = Direction.outbound if from_handle in self_handles else Direction.inbound

    return Envelope(
        channel=Channel.outlook,
        external_id=raw["internetMessageId"],
        thread_external_id=raw.get("conversationId", ""),
        direction=direction,
        sent_at=raw["receivedDateTime"],
        from_handle=from_handle,
        to_handles=to_handles,
        from_display_name=from_addr.get("name") or None,
        to_display_names=[a.get("name") or None for a in to_addrs],
        subject=raw.get("subject"),
        body_text=_strip_html(raw.get("body", {})),
        is_group=len(to_handles) > 1,
        is_automated=False,  # parser tier 1 sets this later (§9) — out of
                             # scope for the adapter itself
        raw=raw,
    )


def run() -> None:
    load_dotenv()
    self_email = os.environ["OUTLOOK_MAILBOX"].lower()
    delta_link = DELTA_LINK_PATH.read_text().strip() if DELTA_LINK_PATH.exists() else None

    next_delta_link = None
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        gen = fetch_messages(delta_link=delta_link)
        count = 0
        while True:
            # NOT `for raw in gen:` — that swallows the generator's return
            # value. fetch_messages() returns the next delta link via
            # `return`, which only surfaces through StopIteration.value on
            # manual next() calls. A for-loop never exposes it — found
            # while self-reviewing before the first git push: every past
            # run of this adapter has been silently doing a full mailbox
            # backfill instead of an incremental delta sync.
            try:
                raw = next(gen)
            except StopIteration as e:
                next_delta_link = e.value
                break
            env = _to_envelope(raw, self_handles={self_email})
            if env is None:
                continue
            upsert(conn, env, self_email)
            count += 1
        conn.commit()

    if next_delta_link:
        DELTA_LINK_PATH.write_text(next_delta_link)

    print(f"synced {count} messages")  # noqa: T201


if __name__ == "__main__":
    run()
