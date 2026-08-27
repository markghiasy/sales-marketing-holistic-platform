"""Outlook adapter entrypoint: pull from Graph, normalise to the envelope,
upsert into the store. Full backfill on first run, delta thereafter.

Run: python -m adapters.outlook.sync
"""

from __future__ import annotations

import html
import os
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from ..envelope import Channel, Direction, Envelope
from ..store_writer import upsert
from .client import fetch_messages

# One delta link per folder — each folder's delta query is its own
# independent paging sequence, so they can't share a single cursor.
_FOLDERS = ("inbox", "sentitems")
_DELTA_LINK_PATHS = {
    folder: Path(__file__).parent / f".delta_link.{folder}.txt" for folder in _FOLDERS
}
# pre-existing single-folder cursor from before Sent was added — migrated
# to the new per-folder name below so a re-run doesn't silently re-backfill
# the whole inbox from scratch.
_LEGACY_INBOX_DELTA_LINK_PATH = Path(__file__).parent / ".delta_link.txt"
_TAG_RE = re.compile(r"<[^>]+>")

# Where a quoted reply chain starts, checked against this mailbox's real
# HTML bodies (2026-08-28) before picking these rather than assuming
# Outlook's own convention would dominate: divRplyFwdMsg (Outlook's own
# "reply/forward" marker) appeared in only 0.7% of messages here — this
# mailbox is Gmail-seeded test data, so gmail_quote (7.2%) and bare
# <blockquote> (8.2%, catches other clients that wrap quotes without
# Gmail's specific class) are what actually matter for real coverage.
# Order matters: first match found wins, everything from there on is cut.
_QUOTE_START_RE = re.compile(
    # class="gmail_quote" alone is rare in practice — real messages here
    # overwhelmingly pair it with a second class (class="gmail_quote
    # gmail_quote_container") or prefix it (class="x_gmail_quote"), so
    # this matches gmail_quote appearing anywhere inside a class
    # attribute rather than requiring it to be the whole value —
    # confirmed against real data after the exact-match version silently
    # missed 25 of 27 real gmail_quote messages.
    r'id="divRplyFwdMsg"|class="[^"]*gmail_quote|<blockquote',
    re.IGNORECASE,
)
# Plain-text fallback (103 of 4,769 real messages here are contentType
# "text", not "html") — "On <date>, <name> wrote:" is the cross-client
# convention for where quoted history starts in a plain-text body.
_QUOTE_START_TEXT_RE = re.compile(r"^On .{5,80} wrote:\s*$", re.MULTILINE)


def _strip_html(body: dict) -> str:
    """Graph returns body as {contentType, content}. Plain-text it and cut
    the quoted-reply chain — §6 calls for a clean body, needed for both
    later extraction and the voice corpus (Block E)."""
    content = body.get("content", "") or ""
    if body.get("contentType") == "html":
        match = _QUOTE_START_RE.search(content)
        if match:
            content = content[: match.start()]
        content = _TAG_RE.sub(" ", content)
        content = html.unescape(content)
    else:
        match = _QUOTE_START_TEXT_RE.search(content)
        if match:
            content = content[: match.start()]
    return content.strip()


def _resolve_sent_at(raw: dict) -> datetime:
    """Prefer the message's own Date header over Graph's receivedDateTime.

    Found while investigating garbled timestamps on the Gmail-seeded test
    mailbox: New Outlook's .eml importer stamps receivedDateTime with the
    *import* time, not the message's real date — every seeded message
    showed today's date. The original Date header survives untouched
    (confirmed against real data), so it's the trustworthy source whenever
    it's present; receivedDateTime is only a fallback for messages that
    arrived normally (no header available in that shape).
    """
    headers = raw.get("internetMessageHeaders") or []
    date_hdr = next((h["value"] for h in headers if h["name"].lower() == "date"), None)
    if date_hdr:
        try:
            dt = parsedate_to_datetime(date_hdr)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except (TypeError, ValueError):
            pass  # malformed header — fall through
    return datetime.fromisoformat(raw["receivedDateTime"])


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
        sent_at=_resolve_sent_at(raw),
        from_handle=from_handle,
        to_handles=to_handles,
        from_display_name=from_addr.get("name") or None,
        to_display_names=[a.get("name") or None for a in to_addrs],
        subject=raw.get("subject"),
        body_text=_strip_html(raw.get("body", {})),
        is_group=len(to_handles) > 1,
        # §9 tier 1's own table names this exact signal: "Graph's own
        # Focused/Other classification. Sets is_automated at ingest." Not
        # the full tier-1 ruleset (List-Unsubscribe header, known
        # automated domains, bulk-sender patterns) — those still belong
        # to the real Block B noise-parser build — just this one field,
        # since Graph already computes it and hands it back for free.
        is_automated=raw.get("inferenceClassification") == "other",
        raw=raw,
    )


def _migrate_legacy_inbox_delta_link() -> None:
    if _LEGACY_INBOX_DELTA_LINK_PATH.exists() and not _DELTA_LINK_PATHS["inbox"].exists():
        _DELTA_LINK_PATHS["inbox"].write_text(_LEGACY_INBOX_DELTA_LINK_PATH.read_text())


def run() -> None:
    load_dotenv()
    self_email = os.environ["OUTLOOK_MAILBOX"].lower()
    _migrate_legacy_inbox_delta_link()

    count = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for folder in _FOLDERS:
            delta_link_path = _DELTA_LINK_PATHS[folder]
            delta_link = delta_link_path.read_text().strip() if delta_link_path.exists() else None

            next_delta_link = None
            gen = fetch_messages(folder=folder, delta_link=delta_link)
            while True:
                # NOT `for raw in gen:` — that swallows the generator's
                # return value. fetch_messages() returns the next delta
                # link via `return`, which only surfaces through
                # StopIteration.value on manual next() calls. A for-loop
                # never exposes it — found while self-reviewing before the
                # first git push: every past run of this adapter had been
                # silently doing a full mailbox backfill instead of an
                # incremental delta sync.
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

            if next_delta_link:
                delta_link_path.write_text(next_delta_link)
        conn.commit()

    print(f"synced {count} messages")


if __name__ == "__main__":
    run()
