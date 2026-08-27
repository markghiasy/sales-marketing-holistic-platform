"""Read the LinkedIn messaging inbox by listening to the page's own network
traffic, human-paced.

Why network interception instead of scraping the rendered DOM: LinkedIn's
own frontend fetches messages from internal `voyagerMessagingGraphQL`
endpoints and *renders* what we were scraping before. Those responses carry
a stable `entityUrn` per message and a real epoch timestamp — both missing
from the DOM. This module drives a normal, logged-in Playwright session
(your own cookies, your own account) and reads the responses the page
already makes as it loads; it does not construct or replay requests itself.

Verified against a real live message (2026-08-28): the response shape
guessed from LinkedIn's documented RestLi/GraphQL conventions (`included`
array, `$type` filtering) was wrong. The real shape is
`data.messengerMessagesBySyncToken.elements[]`, each element a Message
object directly — no `included` array, no `$type` filtering needed. Text
is at `body.text`, the sender's real id at `sender.hostIdentityUrn`, and
usefully, `conversation.entityUrn` embeds *your own* profile urn as its
first component (`urn:li:msg_conversation:(<your urn>, <thread id>)`) —
so "who am I" no longer needs a separately-configured member id at all,
see `_self_urn_from_conversation_urn`.

Both lists on the messaging page (conversations, and each thread's message
history) are virtualized — `_collect_conversation_hrefs` and
`_scroll_thread_history` scroll and re-check until nothing new shows up or
`max_scroll_attempts` (§config) is hit, rather than only reading whatever
happened to be rendered on first load.
"""

from __future__ import annotations

import random
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..envelope import Channel, Direction, Envelope
from .config import RateLimits
from .config import load as load_config
from .session_limit import record_session

STORAGE_STATE_PATH = Path(__file__).parent / ".storage_state.json"

_MESSAGES_QUERY = "messengerMessages"

# `conversation.entityUrn` looks like
# "urn:li:msg_conversation:(urn:li:fsd_profile:ACoAAD...,2-OTgw...)" — the
# first component is always *your own* profile urn, confirmed against a
# real live message (2026-08-28). Using this instead of a configured
# member id sidesteps a real bug: the old LINKEDIN_MEMBER_ID scheme took
# the vanity slug from a profile URL (e.g. "evang2"), which is not the
# internal fsd_profile id LinkedIn's own payloads use at all — comparing
# the two never matched, so every message silently looked inbound.
_CONVERSATION_SELF_URN_RE = re.compile(r"^urn:li:msg_conversation:\((?P<self>urn:li:fsd_profile:[^,]+),")


def _pace(limits: RateLimits) -> None:
    time.sleep(random.uniform(limits.min_delay_seconds, limits.max_delay_seconds))


def _epoch_ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _self_urn_from_conversation_urn(conversation_urn: str) -> str | None:
    m = _CONVERSATION_SELF_URN_RE.match(conversation_urn)
    return m.group("self") if m else None


def _extract_messages(payload: dict) -> list[dict]:
    """Pull message entities out of a messengerMessages response.

    Real shape (verified 2026-08-28, see module docstring):
    data.messengerMessagesBySyncToken.elements[] — each element is a
    Message object directly, no `included` array, no `$type` filtering.
    """
    elements = (
        payload.get("data", {})
        .get("messengerMessagesBySyncToken", {})
        .get("elements", [])
    )
    out = []
    for msg in elements:
        text = (msg.get("body") or {}).get("text")
        if not text:
            continue

        sender = msg.get("sender") or {}
        sender_urn = sender.get("hostIdentityUrn") or sender.get("entityUrn", "")
        conversation_urn = (msg.get("conversation") or {}).get("entityUrn", "")

        out.append({
            "message_urn": msg.get("entityUrn", ""),
            "conversation_urn": conversation_urn,
            "body_text": text,
            "sender_urn": sender_urn,
            "created_at_ms": msg.get("deliveredAt"),
        })
    return out


_CONVERSATION_ITEM_SELECTOR = "div.msg-conversation-listitem__link"


def _count_conversation_items(page: Page, limits: RateLimits) -> int:
    """Both lists on this page are virtualized — items outside the viewport
    aren't in the DOM at all, so a single query only sees what's currently
    rendered. Scroll the list container and re-query until the count stops
    growing (or we hit the attempt budget), same pattern as
    `_scroll_thread_history` below.

    Verified 2026-08-28 against a real live message: conversation rows are
    NOT `<a href>` links (an earlier version of this file assumed
    `a[href*="/messaging/thread/"]`, which matched nothing — LinkedIn
    routes these client-side off a click handler on a plain `<div>`
    instead, no href to read at all). `fetch_conversations` below clicks
    each one by position rather than navigating to a URL.
    """
    scroller = page.query_selector("ul.msg-conversations-container__conversations-list")
    if scroller is None:
        return 0

    count = len(page.query_selector_all(_CONVERSATION_ITEM_SELECTOR))
    for _ in range(limits.max_scroll_attempts):
        if count >= limits.max_pages_per_session:
            return limits.max_pages_per_session
        scroller.evaluate("el => el.scrollTo(0, el.scrollHeight)")
        time.sleep(limits.scroll_pause_seconds)
        new_count = len(page.query_selector_all(_CONVERSATION_ITEM_SELECTOR))
        if new_count == count:
            break  # scrolling didn't surface anything new — bottom reached
        count = new_count

    return min(count, limits.max_pages_per_session)


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


def fetch_conversations(page: Page, limits: RateLimits):
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
        captured.extend(_extract_messages(payload))

    page.on("response", on_response)

    page.goto("https://www.linkedin.com/messaging/")
    page.wait_for_selector("ul.msg-conversations-container__conversations-list")
    _pace(limits)

    item_count = _count_conversation_items(page, limits)

    for i in range(item_count):
        captured.clear()
        # re-query fresh each time rather than keeping element handles from
        # the scroll pass above — virtualization can recycle/detach DOM
        # nodes as the list scrolls, and a stale handle's .click() either
        # errors or silently clicks the wrong row
        items = page.query_selector_all(_CONVERSATION_ITEM_SELECTOR)
        if i >= len(items):
            break  # list shrank (e.g. a conversation got removed) — stop rather than index into nothing
        items[i].click()
        try:
            page.wait_for_selector("li.msg-s-message-list__event", timeout=15_000)
        except PlaywrightTimeoutError:
            # some conversation types (a bare connection-request preview,
            # LinkedIn's own automated threads) don't render this list at
            # all — found empirically 2026-08-28: this selector reliably
            # appears for a normal message thread, but not every row in
            # the inbox is one. Skip this row rather than crash the whole
            # session over one conversation type nobody anticipated.
            _pace(limits)
            continue
        _pace(limits)  # let the initial page of messages land before scrolling

        _scroll_thread_history(page, limits, captured)

        if not captured:
            continue

        # Which thread these responses belong to is ground-truthed from
        # the response payload itself (conversation_urn), not guessed
        # from the href's own encoding — simpler and can't drift out of
        # sync with however LinkedIn happens to encode the URL that day.
        # A response from the *previous* thread's page can still land
        # late after captured.clear(); this filters those out too.
        thread_urn = captured[0]["conversation_urn"]
        seen_urns: set[str] = set()
        for msg in captured:
            if msg.get("conversation_urn") != thread_urn:
                continue
            urn = msg.get("message_urn")
            if not urn or urn in seen_urns:
                continue  # no id to dedupe on, or scrolling re-fired an
                          # overlapping response — either way skip
            seen_urns.add(urn)
            msg["thread_id"] = thread_urn
            yield msg

        _pace(limits)


def _to_envelope(raw: dict) -> Envelope | None:
    if not raw.get("message_urn"):
        return None  # no stable id — drop rather than guess one (unlike
                      # the DOM-scraping version this replaces)

    self_urn = _self_urn_from_conversation_urn(raw.get("conversation_urn") or "")
    if self_urn is None:
        return None  # can't tell direction without it — drop rather than guess

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


def run(headless: bool = True):
    """Yields envelopes as they're scraped (one browser session, generator
    all the way through) rather than collecting everything into a list
    first — so a crash partway through a run doesn't throw away whatever
    was already pulled. `sync.py` upserts each one as it arrives instead
    of waiting for this to finish.
    """
    limits = load_config()
    record_session(limits.max_sessions_per_day)  # raises SessionLimitExceeded
                                                   # before a browser ever
                                                   # opens if today's cap
                                                   # is already spent
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()

        for raw in fetch_conversations(page, limits):
            env = _to_envelope(raw)
            if env is not None:
                yield env

        browser.close()
