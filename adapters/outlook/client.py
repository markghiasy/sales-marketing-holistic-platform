"""Thin Graph API client: auth (device code, cached) + raw message fetch.

Nothing here knows about the store schema — this module's only job is to
hand back Graph JSON. envelope.py is the only thing allowed to interpret it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]
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


def get_access_token() -> str:
    """Cached token if it's still valid; device-code prompt otherwise."""
    if TOKEN_CACHE_PATH.exists():
        cached = json.loads(TOKEN_CACHE_PATH.read_text())
        if cached.get("scopes") == SCOPES and cached.get("expires_at", 0) > time.time() + 60:
            return cached["access_token"]

    device_code_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
    resp = requests.post(
        device_code_url,
        data={"client_id": GRAPH_CLI_CLIENT_ID, "scope": " ".join(SCOPES)},
        timeout=30,
    )
    resp.raise_for_status()
    flow = resp.json()
    print(flow["message"])

    # Polling by hand, straight against the token endpoint (RFC 8628) —
    # msal's own device-flow helpers (both initiate_device_flow +
    # acquire_token_by_device_flow, and hand-wrapping the latter in a
    # retry loop) were unreliable in this environment, returning
    # "authorization_pending" as a terminal result after a single poll.
    token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    interval = flow.get("interval", 5)
    deadline = time.time() + flow.get("expires_in", 900)
    result = {"error": "authorization_pending"}
    while result.get("error") == "authorization_pending" and time.time() < deadline:
        time.sleep(interval)
        resp = requests.post(
            token_url,
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

    TOKEN_CACHE_PATH.write_text(json.dumps({
        "access_token": result["access_token"],
        "scopes": SCOPES,
        "expires_at": time.time() + result.get("expires_in", 3600),
    }))
    return result["access_token"]


_SELECT_FIELDS = (
    "subject,body,from,toRecipients,receivedDateTime,"
    "internetMessageId,id,conversationId,internetMessageHeaders"
)


def _walk(url: str, headers: dict):
    """Follows @odata.nextLink to exhaustion, yielding every item. Returns
    the final page's @odata.deltaLink, if any, via the generator's return
    value."""
    next_delta_link = None
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        yield from data.get("value", [])
        url = data.get("@odata.nextLink")
        if "@odata.deltaLink" in data:
            next_delta_link = data["@odata.deltaLink"]
    return next_delta_link


def fetch_messages(delta_link: str | None = None, page_size: int = 50):
    """Yields raw Graph message dicts. Returns the next delta_link via the
    generator's return value (see sync.py for how that's consumed).

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
        f"{GRAPH_BASE}/me/mailFolders/inbox/messages"
        f"?$top={page_size}&$select={_SELECT_FIELDS}"
    )
    yield from _walk(plain_url, headers)

    delta_seed_url = (
        f"{GRAPH_BASE}/me/mailFolders/inbox/messages/delta"
        f"?$top={page_size}&$select={_SELECT_FIELDS}"
    )
    seed_gen = _walk(delta_seed_url, headers)
    while True:
        try:
            next(seed_gen)  # discard — already have everything from the plain pass
        except StopIteration as e:
            return e.value
