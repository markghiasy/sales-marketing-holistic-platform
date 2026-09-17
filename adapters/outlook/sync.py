"""Outlook adapter entrypoint: pull from Graph, normalise to the envelope,
upsert into the store. Full backfill on first run, delta thereafter.

Run: python -m adapters.outlook.sync
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from ..ai_brief import person_keys_for_identities, refresh_touched_best_effort
from ..envelope import Channel, Direction, Envelope
from ..store_writer import upsert
from .client import fetch_messages

# Answers a question message-staleness alone can't: "did the sync itself
# actually run and finish" is a different question from "did any new mail
# land" — a mailbox can genuinely go quiet for a day or more even when the
# adapter is working fine, and conflating the two flagged this mailbox
# unhealthy on 2026-09-08 despite the scheduled task succeeding every
# 10 minutes throughout. Same fix already applied to LinkedIn on
# 2026-09-02 for the identical reason — see adapters/linkedin/sync.py and
# scripts/monitor.py's _check_sync_status for the read side of this file.
STATUS_PATH = Path(__file__).parent / ".sync_status.json"


def _write_status(state: str, detail: str) -> None:
    STATUS_PATH.write_text(json.dumps({
        "state": state,
        "detail": detail,
        "at": datetime.now(UTC).isoformat(),
    }))


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
# Real bug found 2026-09-17: _TAG_RE alone only strips the <style>/
# <script> tags themselves, leaving everything between them (raw CSS
# rules, raw JS) as plain visible text — confirmed against real
# marketing emails (e.g. Transport Victoria, Holly from Startmate) with
# genuinely clean, uncorrupted <style> blocks. Must remove the whole
# block, tag and content together, before the generic tag strip runs.
_STYLE_OR_SCRIPT_BLOCK_RE = re.compile(r"<(style|script)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)

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
# Gmail signature blocks (data-smartmail="gmail_signature", or a class
# attribute containing "gmail_signature") sit at the end of real message
# content, like the quote chain above — checked against 96 real messages
# containing this marker (2026-09-17): in every sample, nothing after it
# was real content. They're also exactly the part of these messages most
# prone to Graph-side quoted-printable corruption (deeply nested HTML
# tables) — when corruption eats the opening "<" of a nested tag inside
# one, it turns into a literal "=", so _TAG_RE can no longer recognise it
# as a tag at all, and garbage like `=span style="...">` leaks straight
# into the visible message text. Cutting the whole block from its first
# occurrence — same approach as _QUOTE_START_RE — discards it wholesale
# rather than trying to parse markup that's already lost information.
_SIGNATURE_START_RE = re.compile(
    r'data-smartmail="gmail_signature"|class="[^"]*gmail_signature',
    re.IGNORECASE,
)

# Plain-text fallback (103 of 4,769 real messages here are contentType
# "text", not "html") — "On <date>, <name> wrote:" is the cross-client
# convention for where quoted history starts in a plain-text body.
_QUOTE_START_TEXT_RE = re.compile(r"^On .{5,80} wrote:\s*$", re.MULTILINE)

# §9 tier 1: sender local-part patterns that mark automated mail —
# separate list from any "generic role address" concept used elsewhere
# (identity resolution's safety checks) — this list means "this sender
# is a machine," not "this address might be shared by several humans."
_AUTOMATED_SENDER_PATTERNS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "notifications", "notification", "alerts", "alert",
    "mailer-daemon", "postmaster",
})

# §9 tier 1: known automated/ESP sending domains. Checked against 4,769
# real ingested Outlook messages: matched 0 of them. ESPs (SendGrid,
# Mailgun, etc.) relay under the customer's own domain in the `From:`
# header — the thing this check looks at — not under their own domain;
# an ESP's own domain shows up in `Return-Path` instead, which isn't
# available here (the Envelope/raw payload this code sees carries only
# `from_handle`, no return-path headers). Left in place since a future
# sender could still match (e.g. a company's own bulk-mail subdomain) —
# extend with a one-line diff if real automated senders are seen that
# this list misses.
_AUTOMATED_SENDER_DOMAINS = frozenset({
    "sendgrid.net", "mailgun.org", "amazonses.com",
    "mailchimp.com", "notifications.google.com",
})


def _sender_looks_automated(from_handle: str) -> bool:
    local_part, _, domain = from_handle.partition("@")
    if local_part.lower() in _AUTOMATED_SENDER_PATTERNS:
        return True
    return domain.lower() in _AUTOMATED_SENDER_DOMAINS


def is_automated(raw: dict, from_handle: str) -> bool:
    """§9 tier 1, combined via OR — any one signal is enough:
    - Graph's own Focused/Other classification (free, already computed)
    - a List-Unsubscribe header (bulk/marketing mail marks itself)
    - sender local-part or domain patterns that indicate automation

    Pulled out of _to_envelope so a backfill can recompute this against
    already-ingested messages' stored `raw` payload without needing to
    re-derive from_handle or duplicate the OR expression in a second
    place — see scripts/backfill_is_automated.py.
    """
    headers = raw.get("internetMessageHeaders") or []
    has_list_unsubscribe = any(h.get("name", "").lower() == "list-unsubscribe" for h in headers)
    return (
        raw.get("inferenceClassification") == "other"
        or has_list_unsubscribe
        or _sender_looks_automated(from_handle)
    )


# Some marketing/notification emails' invisible "preview text" padding
# (zero-width characters used to hide preheader text from bulk-mail spam
# filters) arrive from Graph itself already mangled — confirmed 2026-09-17
# against real production mail: raw.body.content already contains stray
# replacement characters interleaved with undecoded quoted-printable byte
# escapes (e.g. "=E2��", "�=80�") *before* any of our
# own code touches it. The original bytes are gone by the time Graph hands
# them to us — not recoverable, not something quopri.decodestring() can
# fix (tried against real data: it also corrupts genuine "=" occurrences
# elsewhere in the same message, e.g. legitimate query-string parameters).
#
# Two-pass cleanup, verified against a real captured sample:
# 1. These specific invisible/placeholder characters are never meaningful
#    visible content regardless of context — safe to remove unconditionally.
#    U+034F COMBINING GRAPHEME JOINER, U+00A0 NBSP, U+200B/C/D ZERO WIDTH
#    SPACE/NON-JOINER/JOINER, U+FEFF BOM, U+FFFD REPLACEMENT CHARACTER.
# 2. Once those are gone, what's left of the garbled block is a run of
#    plain "=XX" tokens separated only by whitespace — a shape normal
#    prose or a URL never produces (a single isolated "=XX", as in a
#    query-string parameter, is common and legitimate; only a RUN of
#    several separated purely by whitespace is garbage). Delete those
#    runs; a single stray "=XX" elsewhere is left untouched.
_GARBLED_INVISIBLE_CHARS_RE = re.compile("[͏ \u200b‌‍﻿�]")
_GARBLED_QP_RUN_RE = re.compile(r"(?:=[0-9A-Fa-f]{2}\s+){2,}=[0-9A-Fa-f]{2}")


def _strip_html(body: dict) -> str:
    """Graph returns body as {contentType, content}. Plain-text it and cut
    the quoted-reply chain — §6 calls for a clean body, needed for both
    later extraction and the voice corpus (Block E)."""
    content = body.get("content", "") or ""
    content = _GARBLED_INVISIBLE_CHARS_RE.sub("", content)
    content = _GARBLED_QP_RUN_RE.sub(" ", content)
    if body.get("contentType") == "html":
        # Both patterns can match mid-attribute (e.g. id="divRplyFwdMsg"
        # or class="gmail_signature" partway through a <div ...> tag), so
        # cutting at the match's own start leaves the tag's opening "<..."
        # dangling with no closing ">" — it survives _TAG_RE untouched
        # since that regex requires both. Found 2026-09-17 while fixing
        # the gmail_signature case; walk back to the tag's real opening
        # "<" so the whole tag is discarded, not just the part from the
        # matched attribute onward.
        cut_points = []
        for match in (_QUOTE_START_RE.search(content), _SIGNATURE_START_RE.search(content)):
            if not match:
                continue
            tag_start = content.rfind("<", 0, match.start())
            cut_points.append(tag_start if tag_start != -1 else match.start())
        if cut_points:
            content = content[: min(cut_points)]
        content = _STYLE_OR_SCRIPT_BLOCK_RE.sub(" ", content)
        content = _TAG_RE.sub(" ", content)
        content = html.unescape(content)
        # Some senders' own tooling (e.g. Gmail's "<name> reacted via
        # Gmail" auto-notifications on a Slack/email thread) sends a real
        # tag *HTML-escaped* — literal "&lt;p&gt;" in the source, not a
        # real "<p>" — so the first pass above never sees it as a tag
        # (no literal "<" yet), and unescaping only turns it into a real
        # "<p>" afterward, too late to be stripped. A second pass here
        # catches exactly that. Safe against the "<3" case (see
        # test_html_entities_unescaped): a lone "<3" with no matching
        # ">" anywhere after it never forms a complete tag, so this
        # second pass leaves it untouched.
        content = _TAG_RE.sub(" ", content)
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
    cc_addrs = [r.get("emailAddress", {}) for r in raw.get("ccRecipients", [])]
    cc_handles = [(a.get("address") or "").lower() for a in cc_addrs]

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
        cc_handles=cc_handles,
        cc_display_names=[a.get("name") or None for a in cc_addrs],
        subject=raw.get("subject"),
        body_text=_strip_html(raw.get("body", {})),
        is_group=len(to_handles) > 1,
        is_automated=is_automated(raw, from_handle),
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
    touched_identity_ids: set[str] = set()
    try:
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
                    identity_id = upsert(conn, env, self_email)
                    touched_identity_ids.add(identity_id)
                    count += 1

                if next_delta_link:
                    delta_link_path.write_text(next_delta_link)
            conn.commit()
    except Exception as e:  # record the real failure, then let it surface
        _write_status("error", f"sync failed: {e}")
        raise

    _write_status("ok", f"synced {count} messages")
    print(f"synced {count} messages")

    from ..resolution.run import run_best_effort as _run_resolution
    _run_resolution()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        person_keys = person_keys_for_identities(cur, touched_identity_ids)
    refresh_touched_best_effort(person_keys)


if __name__ == "__main__":
    run()
