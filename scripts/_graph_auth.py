"""Shared device-code auth for the one-off Graph diagnostic scripts in
this directory. Not msal's own token cache (msal.SerializableTokenCache
never accepted the raw device-code HTTP response cleanly — every script
so far skipped caching and made the user log in again each time). This
just stores the raw token response as JSON with an expiry check, which is
all a short-lived diagnostic session actually needs.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

GRAPH_CLI_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
_CACHE_PATH = Path(__file__).parent / ".graph_token_cache.json"
_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
_DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"


def get_access_token(scopes: list[str]) -> str:
    if _CACHE_PATH.exists():
        cached = json.loads(_CACHE_PATH.read_text())
        if cached.get("scopes") == scopes and cached.get("expires_at", 0) > time.time() + 60:
            return cached["access_token"]

    resp = requests.post(
        _DEVICE_CODE_URL,
        data={"client_id": GRAPH_CLI_CLIENT_ID, "scope": " ".join(scopes)},
        timeout=30,
    )
    resp.raise_for_status()
    flow = resp.json()
    print(flow["message"])

    interval = flow.get("interval", 5)
    deadline = time.time() + flow.get("expires_in", 900)
    result = {"error": "authorization_pending"}
    while result.get("error") == "authorization_pending" and time.time() < deadline:
        time.sleep(interval)
        resp = requests.post(
            _TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": GRAPH_CLI_CLIENT_ID,
                "device_code": flow["device_code"],
            },
            timeout=30,
        )
        result = resp.json()
    if "access_token" not in result:
        raise RuntimeError(f"auth failed: {result.get('error_description') or result}")

    _CACHE_PATH.write_text(json.dumps({
        "access_token": result["access_token"],
        "scopes": scopes,
        "expires_at": time.time() + result.get("expires_in", 3600),
    }))
    return result["access_token"]
