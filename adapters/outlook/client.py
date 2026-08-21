"""Thin Graph API client: auth (device code, cached) + raw message fetch.

Nothing here knows about the store schema — this module's only job is to
hand back Graph JSON. envelope.py is the only thing allowed to interpret it.
"""

from __future__ import annotations

import os
from pathlib import Path

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]
TOKEN_CACHE_PATH = Path(__file__).parent / ".token_cache.bin"


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize())


def get_access_token() -> str:
    """Silent refresh if we have a cached account; device-code prompt otherwise.

    Client id / tenant id come from env only — never hardcode them (build
    plan §5 rule 1: credentials and account identifiers are configuration,
    always, because this repo gets re-hosted at least twice).
    """
    tenant_id = os.environ["AZURE_TENANT_ID"]
    client_id = os.environ["AZURE_CLIENT_ID"]

    cache = _load_cache()
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"device flow failed to start: {flow}")
        print(flow["message"])  # noqa: T201 — deliberate operator-facing prompt
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(f"auth failed: {result.get('error_description')}")
    return result["access_token"]


def fetch_messages(delta_link: str | None = None, page_size: int = 50):
    """Yields raw Graph message dicts, following pagination and, if given a
    delta_link, only what changed since it. Returns the next delta_link via
    the generator's return value (see sync.py for how that's consumed).
    """
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    url = delta_link or (
        f"{GRAPH_BASE}/me/mailFolders/inbox/messages/delta"
        f"?$top={page_size}"
        f"&$select=subject,body,from,toRecipients,receivedDateTime,"
        f"internetMessageId,id,conversationId"
    )

    next_delta_link = None
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for msg in data.get("value", []):
            yield msg
        url = data.get("@odata.nextLink")
        if "@odata.deltaLink" in data:
            next_delta_link = data["@odata.deltaLink"]

    return next_delta_link
