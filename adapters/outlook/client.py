"""Thin Graph API client: auth (device code, cached) + raw message fetch.

Nothing here knows about the store schema — this module's only job is to
hand back Graph JSON. envelope.py is the only thing allowed to interpret it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
# offline_access is what actually gets a refresh_token back in the token
# response — without it, Microsoft's default behaviour for this public
# client can't be relied on to include one, and the whole point of this
# scope list is making the refresh path in get_access_token() work.
# Contacts.Read is for fetch_contacts() (§8's bridge source) — confirmed
# separately (2026-08-27) that this scope authenticates fine against this
# personal mailbox the same way Mail.Read does (no AADSTS530035), so it's
# safe to fold into the same token rather than keeping a second cache.
SCOPES = ["Mail.Read", "offline_access", "Contacts.Read"]
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
# transient — worth a retry with backoff. 401 is deliberately not here: a
# missing/expired token needs a fresh login, not a retry with the same bad
# token.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 4
# a raw JSON cache, not msal.SerializableTokenCache — msal's cache object
# never accepted the token response from the hand-rolled device-code poll
# below cleanly (its .add() wants a shape tied to msal's own request flow),
# so every prior version of this function silently never cached anything
# and re-prompted a login on every run. This just stores what's actually
# needed: the token and when it expires.
TOKEN_CACHE_PATH = Path(__file__).parent / ".token_cache.bin"

# Microsoft's own "Microsoft Graph Command Line Tools" public client —
# first-party, publisher-verified, built for exactly this (script access
# to Graph via device code). Our own app registration kept failing with
# AADSTS530035 ("signed in but no permission") on every auth flow tried
# against this personal Outlook.com mailbox — that's the known failure
# mode for an unverified-publisher app against a personal account. This
# client id isn't a secret (it's published in Microsoft's own docs and
# used by tools worldwide, same idea as Azure CLI's own public client id)
# so — unlike a real credential — hardcoding it here is fine.
GRAPH_CLI_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"


def _save_token_cache(result: dict) -> None:
    # the device-code/refresh token responses both carry a refresh_token
    # when the app is set up for offline access (this public client is) —
    # save it whenever present so an expired access token can be silently
    # renewed instead of forcing a manual device-code login every ~90
    # minutes. Previously only access_token was kept, which meant this
    # adapter could never really run unattended: the first expiry after a
    # human wasn't watching it would just kill the next sync.
    cache = {
        "access_token": result["access_token"],
        "scopes": SCOPES,
        "expires_at": time.time() + result.get("expires_in", 3600),
    }
    if "refresh_token" in result:
        cache["refresh_token"] = result["refresh_token"]
    TOKEN_CACHE_PATH.write_text(json.dumps(cache))


def _refresh_access_token(refresh_token: str) -> dict | None:
    """Returns the token response on success, None if the refresh token
    itself is no longer valid (expired/revoked) — falls back to a fresh
    device-code login in that case rather than raising."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": GRAPH_CLI_CLIENT_ID,
            "refresh_token": refresh_token,
            "scope": " ".join(SCOPES),
        },
        timeout=30,
    )
    result = resp.json()
    if "access_token" not in result:
        return None
    return result


def get_access_token(on_device_code: Callable[[dict], None] | None = None) -> str:
    """Cached token if valid; silently refreshed if expired but a refresh
    token is on hand; device-code prompt only as a last resort.

    on_device_code, if given, is called with the raw device-code flow dict
    right after it's obtained, before the blocking poll loop starts — lets
    a caller (the onboarding dashboard) surface the code/URL to a page
    instead of only the console `print` below.
    """
    cached = None
    if TOKEN_CACHE_PATH.exists():
        cached = json.loads(TOKEN_CACHE_PATH.read_text())
        if cached.get("scopes") == SCOPES and cached.get("expires_at", 0) > time.time() + 60:
            return cached["access_token"]

    if cached and cached.get("scopes") == SCOPES and cached.get("refresh_token"):
        refreshed = _refresh_access_token(cached["refresh_token"])
        if refreshed is not None:
            _save_token_cache(refreshed)
            return refreshed["access_token"]
        # refresh token expired/revoked — fall through to device code

    device_code_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
    resp = requests.post(
        device_code_url,
        data={"client_id": GRAPH_CLI_CLIENT_ID, "scope": " ".join(SCOPES)},
        timeout=30,
    )
    resp.raise_for_status()
    flow = resp.json()
    print(flow["message"])
    if on_device_code is not None:
        on_device_code(flow)

    # Polling by hand, straight against the token endpoint (RFC 8628) —
    # msal's own device-flow helpers (both initiate_device_flow +
    # acquire_token_by_device_flow, and hand-wrapping the latter in a
    # retry loop) were unreliable in this environment, returning
    # "authorization_pending" as a terminal result after a single poll.
    interval = flow.get("interval", 5)
    deadline = time.time() + flow.get("expires_in", 900)
    result = {"error": "authorization_pending"}
    while result.get("error") == "authorization_pending" and time.time() < deadline:
        time.sleep(interval)
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": GRAPH_CLI_CLIENT_ID,
                "device_code": flow["device_code"],
            },
            timeout=30,
        )
        result = resp.json()
    if result.get("error") == "authorization_pending":
        raise RuntimeError("device code expired — no login completed in time")
    if "access_token" not in result:
        raise RuntimeError(f"auth failed: {result.get('error_description') or result}")

    _save_token_cache(result)
    return result["access_token"]


_SELECT_FIELDS = (
    "subject,body,from,toRecipients,receivedDateTime,"
    "internetMessageId,id,conversationId,internetMessageHeaders,"
    "inferenceClassification"
)


def _get_with_retry(url: str, headers: dict) -> requests.Response:
    """A transient Graph error (rate limit, 5xx) used to kill the whole
    sync mid-run instead of just costing a few seconds — a single blip
    partway through a 4700-message backfill meant starting over. Retries
    with exponential backoff, honouring Retry-After when Graph sends one
    (it does on 429s) rather than guessing at a delay."""
    for attempt in range(_MAX_RETRIES + 1):
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code not in _RETRYABLE_STATUS or attempt == _MAX_RETRIES:
            resp.raise_for_status()
            return resp
        retry_after = resp.headers.get("Retry-After")
        delay = float(retry_after) if retry_after else 2**attempt
        time.sleep(delay)
    raise AssertionError("unreachable")  # loop always returns or raises above


def _walk(url: str, headers: dict):
    """Follows @odata.nextLink to exhaustion, yielding every item. Returns
    the final page's @odata.deltaLink, if any, via the generator's return
    value."""
    next_delta_link = None
    while url:
        resp = _get_with_retry(url, headers)
        data = resp.json()
        yield from data.get("value", [])
        url = data.get("@odata.nextLink")
        if "@odata.deltaLink" in data:
            next_delta_link = data["@odata.deltaLink"]
    return next_delta_link


def fetch_messages(folder: str = "inbox", delta_link: str | None = None, page_size: int = 50):
    """Yields raw Graph message dicts from the given mail folder ('inbox' or
    'sentitems' — Graph's well-known folder names). Returns the next
    delta_link via the generator's return value (see sync.py for how
    that's consumed).

    delta_link given: pure incremental sync — only what changed since then.

    delta_link is None (first run): a delta query's very first page looks
    like the start of a full backfill, but for a personal Outlook.com
    mailbox it silently caps out at ~50 items total and hands back a
    deltaLink as if that were everything — found by tracing every page of
    a fresh delta call against a 4769-message inbox and watching it stop
    at 50. So the first run instead does a plain (non-delta) listing,
    which paginates properly with no such cap, to get everything; then
    makes one delta call afterward (yielding nothing new — everything
    from it was already pulled) purely to obtain a real deltaLink to seed
    future incremental runs with.
    """
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    if delta_link:
        return (yield from _walk(delta_link, headers))

    plain_url = (
        f"{GRAPH_BASE}/me/mailFolders/{folder}/messages"
        f"?$top={page_size}&$select={_SELECT_FIELDS}"
    )
    yield from _walk(plain_url, headers)

    delta_seed_url = (
        f"{GRAPH_BASE}/me/mailFolders/{folder}/messages/delta"
        f"?$top={page_size}&$select={_SELECT_FIELDS}"
    )
    seed_gen = _walk(delta_seed_url, headers)
    while True:
        try:
            next(seed_gen)  # discard — already have everything from the plain pass
        except StopIteration as e:
            return e.value


_CONTACTS_SELECT_FIELDS = "id,displayName,emailAddresses,mobilePhone,businessPhones,homePhones"


def fetch_contacts(page_size: int = 50):
    """Yields raw Graph contact dicts from /me/contacts — the whole
    folder, every run (no delta; contact volume is small enough that a
    full refresh each time is simpler than tracking another cursor)."""
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/me/contacts?$top={page_size}&$select={_CONTACTS_SELECT_FIELDS}"
    yield from _walk(url, headers)
