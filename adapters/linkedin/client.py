"""Read the LinkedIn messaging inbox by listening to the page's own network
traffic, human-paced.

Why network interception instead of scraping the rendered DOM: LinkedIn's
own frontend fetches messages from internal `voyagerMessagingGraphQL`
endpoints and *renders* what we were scraping before. Those responses carry
a stable `entityUrn` per message and a real epoch timestamp — both missing
from the DOM. This module drives a normal, logged-in Playwright session
(your own cookies, your own account) and reads the responses the page
already makes as it loads; it does not construct or replay requests itself.

Known gap: the exact response shape below (`included` array, `$type`
filtering) was inferred from LinkedIn's documented RestLi/GraphQL
conventions, not confirmed against a live response in this session — the
CSRF-bearing manual probe needed to confirm it was (correctly) blocked by
Claude Code's safety classifier. **This needs a real run against
`login.py` + a live session before anyone trusts the field names below.**

Both lists on the messaging page (conversations, and each thread's message
history) are virtualized — `_collect_conversation_hrefs` and
`_scroll_thread_history` scroll and re-check until nothing new shows up or
`max_scroll_attempts` (§config) is hit, rather than only reading whatever
happened to be rendered on first load.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page, Response, sync_playwright

from ..envelope import Channel, Direction, Envelope
from .config import RateLimits
from .config import load as load_config

STORAGE_STATE_PATH = Path(__file__).parent / ".storage_state.json"

_MESSAGES_QUERY = "messengerMessages"


def _pace(limits: RateLimits) -> None:
    time.sleep(random.uniform(limits.min_delay_seconds, limits.max_delay_seconds))


def _epoch_ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _to_profile_urn(member_id: str) -> str:
    """LINKEDIN_MEMBER_ID (per the runbook) is the bare id from your own
    profile URL (/in/<this>). Everything pulled from the JSON responses —
    including the `from` field this gets compared against — is a full
    `urn:li:fsd_profile:<id>` URN. Comparing the two formats directly
    always fails, which silently mislabels every self-sent message as
    inbound (found while self-reviewing this file — not caught by any
    test, since nothing had exercised outbound messages yet).
    """
    if member_id.startswith("urn:li:"):
        return member_id
    return f"urn:li:fsd_profile:{member_id}"


def _extract_messages(payload: dict, self_member_id: str) -> list[dict]:
    """Pull message entities out of a messengerMessages response.

    LinkedIn's RestLi convention: `included` is a flat list of entities of
    mixed types, referenced by URN from the top-level `data` block. We only
    want the ones that are actually messages.
    """
    out = []
    for entity in payload.get("included", []):
        entity_type = entity.get("$type", "")
        if "Event" not in entity_type and "Message" not in entity_type:
            continue
        body = entity.get("eventContent", {}).get("attributedBody", {}).get("text") or entity.get("body")
        if not body:
            continue

        sender_urn = (
            entity.get("from", {}).get("com.linkedin.voyager.messaging.MessagingMember", {})
            .get("miniProfile", {}).get("entityUrn", "")
        )
        created_at = entity.get("createdAt") or entity.get("deliveredAt")

        out.append({
            "message_urn": entity.get("entityUrn", ""),
            "conversation_urn": entity.get("*conversation") or entity.get("conversation"),
            "body_text": body,
            "sender_urn": sender_urn,
            "created_at_ms": created_at,
        })
    return out


def _collect_conversation_hrefs(page: Page, limits: RateLimits) -> list[str]:
    """Both lists on this page are virtualized — items outside the viewport
    aren't in the DOM at all, so a single query only sees what's currently
    rendered. Scroll the list container and re-query until the count stops
    growing (or we hit the attempt budget), same pattern as
    `_scroll_thread_history` below.

    Selector note: `a[href*="/messaging/thread/"]` keys off LinkedIn's URL
    routing, not a CSS class — routing structure changes far less often
    than styling, so this is the more durable of the two DOM dependencies
    left in this file (the other being the scroll container itself).
    """
    seen: dict[str, None] = {}  # dict for order-preserving de-dupe
    scroller = page.query_selector("ul.msg-conversations-container__conversations-list")
    if scroller is None:
        return []

    for _ in range(limits.max_scroll_attempts):
        for a in page.query_selector_all('a[href*="/messaging/thread/"]'):
            href = a.get_attribute("href")
            if href:
                seen[href] = None
            if len(seen) >= limits.max_pages_per_session:
                return list(seen.keys())

        before = len(seen)
        scroller.evaluate("el => el.scrollTo(0, el.scrollHeight)")
        time.sleep(limits.scroll_pause_seconds)
        for a in page.query_selector_all('a[href*="/messaging/thread/"]'):
            href = a.get_attribute("href")
            if href:
                seen[href] = None
        if len(seen) == before:
            break  # scrolling didn't surface anything new — bottom reached

    return list(seen.keys())


def _scroll_thread_history(page: Page, limits: RateLimits, captured: list[dict]) -> None:
    """Older messages load as you scroll a thread toward the top — each
    scroll fires another messengerMessages response, picked up by the
    `on_response` listener already attached to the page. This just does
    the scrolling and gives responses time to land; it doesn't read
    `captured` itself.
    """
    scroller = page.query_selector(".msg-s-message-list")
    if scroller is None:
        return

    for _ in range(limits.max_scroll_attempts):
        before = len(captured)
        scroller.evaluate("el => el.scrollTo(0, 0)")
        time.sleep(limits.scroll_pause_seconds)
        if len(captured) == before:
            break  # no new messages arrived — top of history reached


def fetch_conversations(page: Page, limits: RateLimits, self_member_id: str):
    """Yields raw message dicts by loading the inbox and each conversation
    thread, capturing the JSON responses the page makes as it renders."""

    captured: list[dict] = []

    def on_response(response: Response) -> None:
        if _MESSAGES_QUERY not in response.url:
            return
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 — a page's own background
            # traffic can be anything (non-JSON bodies, aborted requests,
            # redirects); the only correct response to a malformed one is
            # to skip it and keep listening, not crash the whole session
            return
        captured.extend(_extract_messages(payload, self_member_id))

    page.on("response", on_response)

    page.goto("https://www.linkedin.com/messaging/")
    page.wait_for_selector("ul.msg-conversations-container__conversations-list")
    _pace(limits)

    hrefs = _collect_conversation_hrefs(page, limits)

    for href in hrefs[: limits.max_pages_per_session]:
        captured.clear()
        page.goto(f"https://www.linkedin.com{href}")
        page.wait_for_selector("li.msg-s-message-list__event", timeout=15_000)
        _pace(limits)  # let the initial page of messages land before scrolling

        _scroll_thread_history(page, limits, captured)

        thread_id = href.strip("/").split("/")[-1]
        seen_urns: set[str] = set()
        for msg in captured:
            urn = msg.get("message_urn")
            if not urn or urn in seen_urns:
                continue  # no id to dedupe on, or scrolling re-fired an
                          # overlapping response — either way skip
            # a response from the previous thread's page can land after
            # `captured.clear()` if it was still in flight — the
            # conversation_urn LinkedIn attaches to each message embeds
            # this thread's id, so check it rather than trusting "arrived
            # between two goto() calls" to mean "belongs to this thread"
            if thread_id not in (msg.get("conversation_urn") or ""):
                continue
            seen_urns.add(urn)
            msg["thread_id"] = thread_id
            yield msg

        _pace(limits)


def _to_envelope(raw: dict, self_member_id: str) -> Envelope | None:
    if not raw.get("message_urn"):
        return None  # no stable id — drop rather than guess one (unlike
                      # the DOM-scraping version this replaces)

    self_urn = _to_profile_urn(self_member_id)
    sender = raw.get("sender_urn") or self_urn
    direction = Direction.outbound if sender == self_urn else Direction.inbound
    sent_at = (
        _epoch_ms_to_dt(raw["created_at_ms"]) if raw.get("created_at_ms") else datetime.now(UTC)
    )

    return Envelope(
        channel=Channel.linkedin,
        external_id=raw["message_urn"],
        thread_external_id=raw["thread_id"],
        direction=direction,
        sent_at=sent_at,
        from_handle=sender,
        to_handles=[self_urn] if direction == Direction.inbound else [],
        subject=None,  # LinkedIn only — Outlook has this, LinkedIn doesn't (§6)
        body_text=raw["body_text"],
        is_group=False,  # not distinguished yet — LinkedIn group messaging
                          # exists but isn't handled here
        is_automated=False,
        raw=raw,
    )


def run(self_member_id: str, headless: bool = True):
    """Yields envelopes as they're scraped (one browser session, generator
    all the way through) rather than collecting everything into a list
    first — so a crash partway through a run doesn't throw away whatever
    was already pulled. `sync.py` upserts each one as it arrives instead
    of waiting for this to finish.
    """
    limits = load_config()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()

        for raw in fetch_conversations(page, limits, self_member_id):
            env = _to_envelope(raw, self_member_id)
            if env is not None:
                yield env

        browser.close()
