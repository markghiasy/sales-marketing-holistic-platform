"""One-off: delete the Gmail-seed junk (promo/spam/job-alert noise) that
just got imported into the Phase 1 test Outlook mailbox via New Outlook's
.eml importer.

Separate from adapters/outlook/client.py on purpose: that module is scoped
to Mail.Read (least privilege for the actual sync adapter) and this needs
Mail.ReadWrite to delete. Uses its own token cache so it doesn't touch the
adapter's cached read-only token.

Input: adapters/whatsapp/node/../.. — no, actually:
  gmail_export/drop_message_ids.json — RFC822 Message-IDs (with angle
  brackets) to delete, built from the local .eml files' own headers.

Deletes go to Deleted Items (Graph's default message DELETE behavior),
not a permanent purge.

Run: python -m scripts.cleanup_seed_inbox
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import msal
import requests
from dotenv import load_dotenv

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.ReadWrite"]
TOKEN_CACHE_PATH = Path(__file__).parent.parent / "adapters" / "outlook" / ".token_cache_readwrite.bin"
DROP_IDS_PATH = Path(__file__).parent.parent.parent / "gmail_export" / "drop_message_ids.json"
ENV_PATH = Path(__file__).parent.parent.parent / ".env.phase1.local"


def _debug_dump_token(access_token: str) -> None:
    """Print the token's own claims (no signature check — diagnostic only)
    so a 401 against Graph can be explained instead of guessed at."""
    import base64
    import json as _json

    try:
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = _json.loads(base64.urlsafe_b64decode(payload_b64))
        print("token claims:", _json.dumps(
            {k: claims.get(k) for k in ("aud", "iss", "scp", "roles", "upn", "unique_name", "tid", "appid")},
            indent=2,
        ))
    except Exception as e:
        print(f"couldn't decode token for debugging: {e}")


#  Microsoft's own "Microsoft Graph Command Line Tools" public client —
# first-party, publisher-verified, pre-built for exactly this scenario
# (script access to Graph via device code). Swapped in after our own
# newly-registered app kept hitting AADSTS530035 ("signed in but no
# permission") on every flow tried — that's the known failure mode for
# unverified-publisher apps against a personal Microsoft account.
GRAPH_CLI_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"


def get_access_token() -> str:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text())

    app = msal.PublicClientApplication(
        GRAPH_CLI_CLIENT_ID,
        # /consumers, not a tenant GUID: a personal Outlook.com mailbox
        # lives on consumer infrastructure, and a tenant-specific
        # authority issues a token that *looks* fine (right audience,
        # right scopes) but still 401s against Graph's mail backend.
        # Found by decoding the token: unique_name was "live.com#..." —
        # the MSA-in-a-directory marker — which is the tell for this.
        authority="https://login.microsoftonline.com/consumers",
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
        print(flow["message"])
        # msal's built-in device-flow polling has been unreliable in this
        # environment (returned "authorization_pending" as terminal after
        # a single poll) — polling by hand instead, straight against the
        # token endpoint, per RFC 8628.
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
        _debug_dump_token(result["access_token"])
        return result["access_token"]

    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize())

    if "access_token" not in result:
        raise RuntimeError(f"auth failed: {result.get('error_description')}")
    return result["access_token"]


def list_all_messages(token: str) -> dict[str, str]:
    """internetMessageId -> Graph message id, for every message in Inbox."""
    headers = {"Authorization": f"Bearer {token}"}
    url = (
        f"{GRAPH_BASE}/me/mailFolders/inbox/messages"
        f"?$select=id,internetMessageId&$top=200"
    )
    mapping: dict[str, str] = {}
    page = 0
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for m in data.get("value", []):
            imid = m.get("internetMessageId")
            if imid:
                mapping[imid] = m["id"]
        page += 1
        if page % 20 == 0:
            print(f"  ...listed {len(mapping)} messages so far")
        url = data.get("@odata.nextLink")
    return mapping


def batch_delete(token: str, message_ids: list[str]) -> tuple[int, int]:
    """Deletes via Graph's $batch endpoint, 20 requests per batch."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    deleted = 0
    failed = 0
    for i in range(0, len(message_ids), 20):
        chunk = message_ids[i : i + 20]
        batch_body = {
            "requests": [
                {"id": str(j), "method": "DELETE", "url": f"/me/messages/{mid}"}
                for j, mid in enumerate(chunk)
            ]
        }
        resp = requests.post(f"{GRAPH_BASE}/$batch", headers=headers, json=batch_body, timeout=30)
        resp.raise_for_status()
        for r in resp.json().get("responses", []):
            if 200 <= r.get("status", 0) < 300:
                deleted += 1
            else:
                failed += 1
        if (i // 20) % 50 == 0:
            print(f"  ...{i + len(chunk)}/{len(message_ids)} processed "
                  f"({deleted} deleted, {failed} failed)")
        time.sleep(0.1)  # gentle pacing, not a rate-limit race
    return deleted, failed


def run() -> None:
    load_dotenv(ENV_PATH)

    drop_ids = json.loads(DROP_IDS_PATH.read_text())
    print(f"{len(drop_ids)} Message-IDs to drop")

    token = get_access_token()

    print("listing all messages in Inbox...")
    mapping = list_all_messages(token)
    print(f"{len(mapping)} messages found in Inbox")

    graph_ids_to_delete = [mapping[mid] for mid in drop_ids if mid in mapping]
    missing = len(drop_ids) - len(graph_ids_to_delete)
    print(f"{len(graph_ids_to_delete)} matched to real Outlook messages, {missing} not found (already gone or not yet synced)")

    deleted, failed = batch_delete(token, graph_ids_to_delete)
    print(f"done: {deleted} deleted, {failed} failed")


if __name__ == "__main__":
    run()
