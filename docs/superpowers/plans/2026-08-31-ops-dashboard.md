# Ops Dashboard (Onboarding + Live Status) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single continuously-running Flask app that lets a non-technical person connect Outlook/LinkedIn/WhatsApp accounts through a web page, and that runs `scripts/monitor.py`'s existing health checks in a background thread so ntfy alerts fire whether or not the page is open.

**Architecture:** One Flask process (`scripts/onboarding/app.py`). Three routes namespaces (`/outlook/*`, `/whatsapp/*`, `/linkedin/*`) wrap the existing adapter auth code unchanged. A `/status` endpoint and a background daemon thread both call the same refactored `monitor.check_all()` function — no duplicated health-check logic. LinkedIn's browser login runs via a standalone helper script (no dependency on this repo) that the user downloads and runs on their own machine, uploading the resulting session file back over HTTP with a single-use token.

**Tech Stack:** Flask (new dependency), existing `adapters.outlook.client`, `adapters.whatsapp` (via subprocess), `scripts/monitor.py`, Playwright (already a dependency, used only inside the standalone LinkedIn helper template).

## Global Constraints

- Single account per channel, system-wide — connecting a new account replaces the existing one; every connect action must confirm first if a connection already exists (design doc, "Error handling").
- No PyInstaller/packaging — the LinkedIn helper assumes Python is already installed on the user's machine; the dashboard states this plainly before the download button.
- Reuse existing adapter auth code and `scripts/monitor.py`'s check functions — no reimplementation of Graph device-code polling, WhatsApp status classification, or staleness checks.
- All user-facing copy (button labels, status text, instructions) is written from the reader's side of the screen — no internal reasoning like "so you don't need to ask Eva" (design doc, "UI copy tone").
- No new persistent store — every "connected" state is derived from the same local files the sync scripts already read (`.token_cache.bin`, `.status.json`, `.storage_state.json`).

---

### Task 1: Extract `check_all()` from `scripts/monitor.py`

**Files:**
- Modify: `scripts/monitor.py:230-262` (the `run()` function)
- Test: `tests/test_monitor.py` (new)

**Interfaces:**
- Produces: `check_all(cur) -> list[ChannelStatus]` — takes an open psycopg cursor, returns the three channels' statuses. `run()` keeps its existing signature and behavior, now implemented in terms of `check_all`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_monitor.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import monitor  # noqa: E402


def test_check_all_returns_three_channel_statuses(monkeypatch):
    cur = MagicMock()
    cur.fetchone.return_value = (None,)  # "no messages ever ingested" for outlook/linkedin
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))

    statuses = monitor.check_all(cur)

    assert [s.channel for s in statuses] == ["outlook", "linkedin", "whatsapp"]
    assert statuses[0].healthy is False  # no messages ever ingested
    assert statuses[2].healthy is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_monitor.py -v`
Expected: FAIL with `AttributeError: module 'monitor' has no attribute 'check_all'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/monitor.py`, replace the body of `run()` (the part between opening the connection and the alert loop) with a call to a new `check_all` function:

```python
def check_all(cur) -> list[ChannelStatus]:
    statuses: list[ChannelStatus] = [
        _check_message_staleness(cur, "outlook"),
        _check_message_staleness(cur, "linkedin"),
    ]
    statuses.append(_check_whatsapp_liveness())
    return statuses


def run() -> int:
    load_dotenv()

    try:
        conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    except Exception as e:  # noqa: BLE001 — report, don't crash the caller
        _send_alert(f"cannot reach store at all: {e}")
        return 1

    with conn, conn.cursor() as cur:
        statuses = check_all(cur)

    alert_state = _load_alert_state()
    now = time.time()
    any_unhealthy = False
    for status in statuses:
        if status.healthy:
            print(f"OK   {status.channel}: {status.detail}")
            alert_state.pop(status.channel, None)  # recovered — reset cooldown
            continue

        any_unhealthy = True
        print(f"FAIL {status.channel}: {status.detail}")
        last_alerted = alert_state.get(status.channel, 0)
        if now - last_alerted > _ALERT_COOLDOWN_HOURS * 3600:
            _send_alert(f"{status.channel} unhealthy — {status.detail}")
            alert_state[status.channel] = now

    _save_alert_state(alert_state)
    return 1 if any_unhealthy else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_monitor.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing suite to confirm nothing broke**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (61 existing + 1 new)

- [ ] **Step 6: Commit**

```bash
git add scripts/monitor.py tests/test_monitor.py
git commit -m "Extract monitor.check_all() so the dashboard can reuse it"
```

---

### Task 2: Add an optional device-code callback to Outlook's `get_access_token()`

**Files:**
- Modify: `adapters/outlook/client.py:89-141`
- Test: `tests/test_outlook_client.py` (new)

**Interfaces:**
- Produces: `get_access_token(on_device_code: Callable[[dict], None] | None = None) -> str`. `on_device_code`, if given, is called with the raw device-code flow dict (`{"message": ..., "user_code": ..., "verification_uri": ..., ...}`) immediately after it's obtained, before the blocking poll loop starts. Existing callers (no argument) are unaffected.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_outlook_client.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from adapters.outlook import client


def test_get_access_token_calls_on_device_code_before_polling(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "TOKEN_CACHE_PATH", tmp_path / ".token_cache.bin")

    device_code_response = MagicMock()
    device_code_response.json.return_value = {
        "message": "go to https://microsoft.com/devicelogin and enter ABC-123",
        "user_code": "ABC-123",
        "verification_uri": "https://microsoft.com/devicelogin",
        "device_code": "raw-device-code",
        "interval": 0,
        "expires_in": 900,
    }
    device_code_response.raise_for_status = MagicMock()

    token_response = MagicMock()
    token_response.json.return_value = {"access_token": "tok", "expires_in": 3600}

    seen = []
    with patch.object(client.requests, "post", side_effect=[device_code_response, token_response]):
        result = client.get_access_token(on_device_code=lambda flow: seen.append(flow))

    assert result == "tok"
    assert seen == [device_code_response.json.return_value]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_outlook_client.py -v`
Expected: FAIL with `TypeError: get_access_token() got an unexpected keyword argument 'on_device_code'`

- [ ] **Step 3: Write minimal implementation**

In `adapters/outlook/client.py`, change the `get_access_token` signature and insert the callback call right after `flow = resp.json()`:

```python
def get_access_token(on_device_code: "Callable[[dict], None] | None" = None) -> str:
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
```

Add `from typing import Callable` to the imports at the top of the file (it's only used in the type hint string above, but add the real import so the hint isn't a string in editors that check it):

```python
from typing import Callable
```

And change the signature's type hint to the real type instead of a string once the import exists:

```python
def get_access_token(on_device_code: Callable[[dict], None] | None = None) -> str:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_outlook_client.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add adapters/outlook/client.py tests/test_outlook_client.py
git commit -m "Let get_access_token() report the device code before it blocks polling"
```

---

### Task 3: Scaffold the Flask app with an app factory and health-check `/status` route

**Files:**
- Create: `scripts/onboarding/__init__.py` (empty)
- Create: `scripts/onboarding/app.py`
- Create: `scripts/onboarding/templates/index.html` (minimal placeholder, filled in fully in Task 7)
- Test: `tests/test_onboarding_app.py` (new)
- Modify: `pyproject.toml:6-12` (add `flask` dependency)

**Interfaces:**
- Produces: `create_app(testing: bool = False) -> Flask` — the app factory. `testing=True` skips starting the background monitor thread and the WhatsApp subprocess check, so tests never spawn real background work.
- Produces: `GET /status` → JSON `{"outlook": {...}, "linkedin": {...}, "whatsapp": {...}}`, each value shaped like `{"healthy": bool, "detail": str}` (straight from `ChannelStatus`).

- [ ] **Step 1: Add Flask to dependencies**

In `pyproject.toml`, change:

```toml
dependencies = [
    "msal>=1.28",
    "requests>=2.32",
    "psycopg[binary]>=3.2",
    "python-dotenv>=1.0",
    "playwright>=1.47",
]
```

to:

```toml
dependencies = [
    "msal>=1.28",
    "requests>=2.32",
    "psycopg[binary]>=3.2",
    "python-dotenv>=1.0",
    "playwright>=1.47",
    "flask>=3.0",
]
```

Run: `.venv/Scripts/python.exe -m pip install -e .`
Expected: Flask installs cleanly.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_onboarding_app.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "onboarding"))

import app as onboarding_app  # noqa: E402
import monitor  # noqa: E402


def test_status_route_returns_all_three_channels(monkeypatch):
    fake_cursor = MagicMock(fetchone=lambda: (None,))
    fake_cursor.connection = MagicMock()
    monkeypatch.setattr(onboarding_app, "_get_status_cursor", lambda: fake_cursor)
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"outlook", "linkedin", "whatsapp"}
    assert body["whatsapp"] == {"healthy": True, "detail": "ok"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 4: Write minimal implementation**

```python
# scripts/onboarding/app.py
"""Ops dashboard: connect Outlook/LinkedIn/WhatsApp through a web page,
and run the same health checks scripts/monitor.py does in a background
thread so alerts fire whether or not this page is open. See
docs/superpowers/specs/2026-08-31-onboarding-dashboard-design.md.

Run: python scripts/onboarding/app.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from flask import Flask, jsonify

# scripts/ isn't an installed package (only adapters* is, see
# pyproject.toml), so import its sibling monitor.py by path — same
# Path(__file__)-relative pattern used throughout this repo's adapters.
sys.path.insert(0, str(Path(__file__).parent.parent))
import monitor  # noqa: E402

_MONITOR_INTERVAL_SECONDS = 15 * 60


def _get_status_cursor():
    """A short-lived connection+cursor for one /status read — separate
    from monitor.run()'s own connection, which the background thread
    manages on its own schedule."""
    conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    return conn.cursor()


def _background_monitor_loop() -> None:
    while True:
        try:
            monitor.run()
        except Exception as e:  # noqa: BLE001 — the loop must survive a bad check
            print(f"background monitor check failed: {e}", file=sys.stderr)
        time.sleep(_MONITOR_INTERVAL_SECONDS)


def create_app(testing: bool = False) -> Flask:
    load_dotenv()
    flask_app = Flask(__name__)

    @flask_app.get("/status")
    def status():
        cur = _get_status_cursor()
        try:
            statuses = monitor.check_all(cur)
        finally:
            cur.connection.close()
        return jsonify({s.channel: {"healthy": s.healthy, "detail": s.detail} for s in statuses})

    if not testing:
        thread = threading.Thread(target=_background_monitor_loop, daemon=True)
        thread.start()

    return flask_app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
```

```html
<!-- scripts/onboarding/templates/index.html -->
<!DOCTYPE html>
<html>
<head><title>Comms Platform — Connect Your Accounts</title></head>
<body>
  <p>Placeholder — filled in with the real three-panel dashboard in Task 7.</p>
</body>
</html>
```

```python
# scripts/onboarding/__init__.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check scripts/onboarding/ adapters/outlook/`
Expected: all pass, no lint errors

- [ ] **Step 7: Commit**

```bash
git add scripts/onboarding/ tests/test_onboarding_app.py pyproject.toml
git commit -m "Scaffold the ops dashboard Flask app with a /status endpoint"
```

---

### Task 4: Outlook connect flow (`/outlook/connect`, `/outlook/status`)

**Files:**
- Modify: `scripts/onboarding/app.py`
- Test: `tests/test_onboarding_app.py`

**Interfaces:**
- Consumes: `adapters.outlook.client.get_access_token(on_device_code=...)` from Task 2; `adapters.outlook.client.TOKEN_CACHE_PATH`.
- Produces: `POST /outlook/connect` → starts the device-code flow in a background thread, returns immediately with `{"status": "already_connected"}` if `TOKEN_CACHE_PATH` already holds a valid-looking cache (a real connection there, per the Global Constraint on confirming before overwrite — the page itself asks the user to confirm, this route just reports the current state so the page can decide whether to show that dialog). `GET /outlook/status` → `{"state": "not_connected" | "pending" | "connected" | "expired", "code": str | None, "url": str | None, "mailbox": str | None}`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_onboarding_app.py

def test_outlook_connect_then_status_shows_pending_code(monkeypatch):
    def fake_get_access_token(on_device_code=None):
        on_device_code({
            "message": "go to https://microsoft.com/devicelogin and enter ABC-123",
            "user_code": "ABC-123",
            "verification_uri": "https://microsoft.com/devicelogin",
        })
        # simulate the flow never completing within this test — the real
        # call blocks in its own background thread, so returning here
        # would normally happen after a real login; the test only checks
        # the pending state that /outlook/status reports meanwhile
        import time as _time
        _time.sleep(0.05)
        return "tok"

    monkeypatch.setattr(onboarding_app.outlook_client, "get_access_token", fake_get_access_token)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post("/outlook/connect")
    assert resp.status_code == 200

    import time as _time
    _time.sleep(0.01)  # let the background thread reach on_device_code
    status_resp = client.get("/outlook/status")
    body = status_resp.get_json()
    assert body["state"] == "pending"
    assert body["code"] == "ABC-123"
    assert body["url"] == "https://microsoft.com/devicelogin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py::test_outlook_connect_then_status_shows_pending_code -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'outlook_client'` (or 404 on the route)

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/onboarding/app.py`, after the existing imports:

```python
from adapters.outlook import client as outlook_client
```

Add module-level state and routes (after `_get_status_cursor`, before `_background_monitor_loop`):

```python
# in-memory only — a real device-code flow is inherently short-lived
# (expires in ~15 min), and this app has no other persistent store, so
# a restart simply means "connect again" rather than needing to survive
# a restart mid-flow
_outlook_state: dict = {"phase": "not_connected"}
_outlook_lock = threading.Lock()


def _outlook_connect_worker() -> None:
    def on_device_code(flow: dict) -> None:
        with _outlook_lock:
            _outlook_state.update(
                phase="pending", code=flow["user_code"], url=flow["verification_uri"]
            )

    try:
        outlook_client.get_access_token(on_device_code=on_device_code)
        with _outlook_lock:
            _outlook_state.update(phase="connected")
    except RuntimeError as e:
        with _outlook_lock:
            state = "expired" if "expired" in str(e) else "error"
            _outlook_state.update(phase=state, error=str(e))
```

Add the two routes inside `create_app`, after the `/status` route:

```python
    @flask_app.post("/outlook/connect")
    def outlook_connect():
        with _outlook_lock:
            _outlook_state.clear()
            _outlook_state["phase"] = "starting"
        threading.Thread(target=_outlook_connect_worker, daemon=True).start()
        return jsonify({"status": "started"})

    @flask_app.get("/outlook/status")
    def outlook_status():
        with _outlook_lock:
            phase = _outlook_state.get("phase", "not_connected")
            code = _outlook_state.get("code")
            url = _outlook_state.get("url")

        if phase in ("not_connected", "starting"):
            return jsonify({"state": phase, "code": None, "url": None, "mailbox": None})
        if phase == "pending":
            return jsonify({"state": "pending", "code": code, "url": url, "mailbox": None})
        if phase == "connected":
            mailbox = os.environ.get("OUTLOOK_MAILBOX")
            return jsonify({"state": "connected", "code": None, "url": None, "mailbox": mailbox})
        return jsonify({"state": phase, "code": None, "url": None, "mailbox": None})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add scripts/onboarding/app.py tests/test_onboarding_app.py
git commit -m "Add Outlook connect flow to the ops dashboard"
```

---

### Task 5: WhatsApp panel (`/whatsapp/connect`, `/whatsapp/status`, `/whatsapp/qr.png`)

**Files:**
- Modify: `scripts/onboarding/app.py`
- Test: `tests/test_onboarding_app.py`

**Interfaces:**
- Consumes: `monitor._WHATSAPP_DIR`, `monitor.WHATSAPP_STATUS_PATH`, `monitor.WHATSAPP_PID_PATH` (Task 1's file, unchanged).
- Produces: `POST /whatsapp/connect` → starts `node ingest.js` as a subprocess if `.pid` doesn't point at a live process (reuses `monitor._pid_is_alive`). `GET /whatsapp/status` → the same shape `.status.json` already has: `{"state": ..., "detail": ..., "at": ...}`, or `{"state": "not_connected"}` if the file doesn't exist yet. `GET /whatsapp/qr.png` → serves the current QR image, or 404 if none exists yet.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_onboarding_app.py
import json


def test_whatsapp_status_reads_status_json(monkeypatch, tmp_path):
    status_path = tmp_path / ".status.json"
    status_path.write_text(json.dumps({"state": "connected", "detail": "connected as 123", "at": "now"}))
    monkeypatch.setattr(monitor, "WHATSAPP_STATUS_PATH", status_path)

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/whatsapp/status")
    assert resp.get_json() == {"state": "connected", "detail": "connected as 123", "at": "now"}


def test_whatsapp_status_not_connected_when_no_status_file(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "WHATSAPP_STATUS_PATH", tmp_path / "missing.json")

    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/whatsapp/status")
    assert resp.get_json() == {"state": "not_connected"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -k whatsapp -v`
Expected: FAIL with 404 (route doesn't exist)

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/onboarding/app.py`, after the outlook routes inside `create_app`:

```python
    @flask_app.get("/whatsapp/status")
    def whatsapp_status():
        if not monitor.WHATSAPP_STATUS_PATH.exists():
            return jsonify({"state": "not_connected"})
        return jsonify(json.loads(monitor.WHATSAPP_STATUS_PATH.read_text()))

    @flask_app.post("/whatsapp/connect")
    def whatsapp_connect():
        pid_text = (
            monitor.WHATSAPP_PID_PATH.read_text().strip()
            if monitor.WHATSAPP_PID_PATH.exists() else ""
        )
        if pid_text and pid_text.isdigit() and monitor._pid_is_alive(int(pid_text)):
            return jsonify({"status": "already_running"})

        subprocess.Popen(
            ["node", "ingest.js"],
            cwd=str(monitor._WHATSAPP_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"status": "started"})

    @flask_app.get("/whatsapp/qr.png")
    def whatsapp_qr():
        qr_path = monitor._WHATSAPP_DIR / "qr.png"
        if not qr_path.exists():
            return jsonify({"error": "no QR available yet"}), 404
        return send_file(qr_path, mimetype="image/png", max_age=0)
```

Add the two new imports needed at the top of `scripts/onboarding/app.py`:

```python
import json
import subprocess

from flask import Flask, jsonify, send_file
```

(replace the existing `from flask import Flask, jsonify` line with the one above).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -k whatsapp -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add scripts/onboarding/app.py tests/test_onboarding_app.py
git commit -m "Add WhatsApp connect flow to the ops dashboard"
```

---

### Task 6: Standalone LinkedIn helper script (runs on the user's own machine)

**Files:**
- Create: `scripts/onboarding/linkedin_helper.py.tmpl`
- Test: `tests/test_linkedin_helper_template.py` (new)

**Interfaces:**
- Produces: a template file with two placeholders, `{{BASE_URL}}` and `{{TOKEN}}`, substituted by Task 7's download route. The resulting script depends only on `playwright` (already documented as a prerequisite) and Python's standard library — nothing from this repo's `adapters` package, since it has to run standalone on a machine that doesn't have this repo checked out.

- [ ] **Step 1: Write the failing test**

This test checks the template is valid Python once placeholders are substituted (it can't actually run a browser login in CI — that part is covered by the manual walkthrough in Task 9).

```python
# tests/test_linkedin_helper_template.py
from __future__ import annotations

import ast
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent.parent / "scripts" / "onboarding" / "linkedin_helper.py.tmpl"


def test_template_is_valid_python_after_substitution():
    template = _TEMPLATE_PATH.read_text()
    filled = template.replace("{{BASE_URL}}", "http://localhost:5000").replace("{{TOKEN}}", "abc123")

    ast.parse(filled)  # raises SyntaxError if the substituted script is broken


def test_template_has_no_leftover_placeholders_after_substitution():
    template = _TEMPLATE_PATH.read_text()
    filled = template.replace("{{BASE_URL}}", "http://localhost:5000").replace("{{TOKEN}}", "abc123")

    assert "{{" not in filled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_linkedin_helper_template.py -v`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write the template**

```python
# scripts/onboarding/linkedin_helper.py.tmpl
"""Connects your LinkedIn account to the Comms Platform.

Double-click this file to run it (or run `python connect_linkedin.py`
from a terminal in this folder if double-clicking doesn't open it).
Requires Python and Playwright's Chrome browser — if this fails with
"playwright not found", run: pip install playwright && playwright install chrome

A real Chrome window will open. Log in to LinkedIn normally, exactly
as you would in any browser. Once you land on your feed, this window
closes itself and your connection finishes automatically.
"""

from __future__ import annotations

import json
import urllib.request

from playwright.sync_api import sync_playwright

BASE_URL = "{{BASE_URL}}"
TOKEN = "{{TOKEN}}"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context(viewport={"width": 1536, "height": 864})
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        print("Log in in the browser window. Waiting for your feed to load...")
        page.wait_for_url("https://www.linkedin.com/feed/**", timeout=300_000)

        storage_state = context.storage_state()
        browser.close()

    print("Login complete — sending your session back to the dashboard...")
    body = json.dumps(storage_state).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/linkedin/upload-session",
        data=body,
        headers={"Content-Type": "application/json", "X-Onboarding-Token": TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status == 200:
            print("Done — you can close this window. The dashboard now shows you as connected.")
        else:
            print(f"Something went wrong sending your session back (HTTP {resp.status}). "
                  f"Please tell whoever sent you this tool.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_linkedin_helper_template.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/onboarding/linkedin_helper.py.tmpl tests/test_linkedin_helper_template.py
git commit -m "Add standalone LinkedIn connection helper template"
```

---

### Task 7: LinkedIn routes (`/linkedin/download-helper`, `/linkedin/upload-session`, `/linkedin/status`)

**Files:**
- Modify: `scripts/onboarding/app.py`
- Test: `tests/test_onboarding_app.py`

**Interfaces:**
- Consumes: `scripts/onboarding/linkedin_helper.py.tmpl` (Task 6), `adapters.linkedin.login.STORAGE_STATE_PATH`.
- Produces: `GET /linkedin/download-helper` → generates a fresh single-use token, returns the filled-in template as a file download named `connect_linkedin.py`. `POST /linkedin/upload-session` (header `X-Onboarding-Token`) → validates the token is known and unused, writes the JSON body to `adapters/linkedin/.storage_state.json`, marks the token used, returns 200 (or 403 for an invalid/reused token). `GET /linkedin/status` → `{"connected": bool}` based on whether `.storage_state.json` exists.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_onboarding_app.py
import secrets


def test_linkedin_download_helper_embeds_a_fresh_token(monkeypatch):
    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.get("/linkedin/download-helper")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "{{TOKEN}}" not in body
    assert "{{BASE_URL}}" not in body
    assert "def main()" in body


def test_linkedin_upload_session_rejects_unknown_token(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding_app.linkedin_login, "STORAGE_STATE_PATH", tmp_path / ".storage_state.json")
    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    resp = client.post(
        "/linkedin/upload-session",
        json={"cookies": []},
        headers={"X-Onboarding-Token": "not-a-real-token"},
    )
    assert resp.status_code == 403


def test_linkedin_upload_session_accepts_valid_token_then_rejects_reuse(tmp_path, monkeypatch):
    storage_path = tmp_path / ".storage_state.json"
    monkeypatch.setattr(onboarding_app.linkedin_login, "STORAGE_STATE_PATH", storage_path)
    flask_app = onboarding_app.create_app(testing=True)
    client = flask_app.test_client()

    download_resp = client.get("/linkedin/download-helper")
    body = download_resp.get_data(as_text=True)
    token = body.split('TOKEN = "')[1].split('"')[0]

    upload_resp = client.post(
        "/linkedin/upload-session",
        json={"cookies": ["fake"]},
        headers={"X-Onboarding-Token": token},
    )
    assert upload_resp.status_code == 200
    assert json.loads(storage_path.read_text()) == {"cookies": ["fake"]}

    reuse_resp = client.post(
        "/linkedin/upload-session",
        json={"cookies": ["fake"]},
        headers={"X-Onboarding-Token": token},
    )
    assert reuse_resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -k linkedin -v`
Expected: FAIL with 404s (routes don't exist)

- [ ] **Step 3: Write minimal implementation**

Add near the top of `scripts/onboarding/app.py`, with the other imports:

```python
import secrets

from flask import request

from adapters.linkedin import login as linkedin_login
```

Add module-level state, near `_outlook_state`:

```python
_linkedin_tokens: dict[str, bool] = {}  # token -> used
_LINKEDIN_HELPER_TEMPLATE_PATH = Path(__file__).parent / "linkedin_helper.py.tmpl"


def _onboarding_base_url() -> str:
    return os.environ.get("ONBOARDING_BASE_URL", "http://localhost:5000")
```

Add the three routes inside `create_app`, after the whatsapp routes:

```python
    @flask_app.get("/linkedin/download-helper")
    def linkedin_download_helper():
        token = secrets.token_urlsafe(24)
        _linkedin_tokens[token] = False
        template = _LINKEDIN_HELPER_TEMPLATE_PATH.read_text()
        script = template.replace("{{BASE_URL}}", _onboarding_base_url()).replace("{{TOKEN}}", token)
        return flask_app.response_class(
            script,
            mimetype="text/x-python",
            headers={"Content-Disposition": "attachment; filename=connect_linkedin.py"},
        )

    @flask_app.post("/linkedin/upload-session")
    def linkedin_upload_session():
        token = request.headers.get("X-Onboarding-Token", "")
        if token not in _linkedin_tokens or _linkedin_tokens[token]:
            return jsonify({"error": "invalid or already-used token"}), 403
        _linkedin_tokens[token] = True
        linkedin_login.STORAGE_STATE_PATH.write_text(json.dumps(request.get_json()))
        return jsonify({"status": "connected"})

    @flask_app.get("/linkedin/status")
    def linkedin_status():
        return jsonify({"connected": linkedin_login.STORAGE_STATE_PATH.exists()})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_onboarding_app.py -k linkedin -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check scripts/onboarding/`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add scripts/onboarding/app.py tests/test_onboarding_app.py
git commit -m "Add LinkedIn connect flow (download helper + session upload) to the ops dashboard"
```

---

### Task 8: The dashboard page — three panels, confirm-before-overwrite, correct UI copy

**Files:**
- Modify: `scripts/onboarding/templates/index.html`
- Manual test only (browser-rendered UI — no automated test for layout/copy; Task 9 covers a real walkthrough)

**Interfaces:**
- Consumes: every JSON endpoint from Tasks 3–7 (`/status`, `/outlook/connect`, `/outlook/status`, `/whatsapp/connect`, `/whatsapp/status`, `/whatsapp/qr.png`, `/linkedin/download-helper`, `/linkedin/status`).

- [ ] **Step 1: Write the full page**

```html
<!-- scripts/onboarding/templates/index.html -->
<!DOCTYPE html>
<html>
<head>
  <title>Comms Platform — Connect Your Accounts</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; }
    .panel { border: 1px solid #ccc; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
    .panel h2 { margin-top: 0; }
    .state { font-weight: 600; }
    .state.connected { color: #2f8f5b; }
    .state.pending, .state.qr_pending { color: #a8791f; }
    .state.error, .state.crashed, .state.logged_out { color: #b1453c; }
    button { padding: 8px 16px; cursor: pointer; }
    img#qr { width: 240px; height: 240px; display: block; margin-top: 8px; }
    code.big { font-size: 1.4em; }
  </style>
</head>
<body>
  <h1>Connect your accounts</h1>
  <p>Connect Outlook, LinkedIn, and WhatsApp below — for your convenience, each one only takes a minute.</p>

  <div class="panel" id="outlook-panel">
    <h2>Outlook</h2>
    <p class="state" id="outlook-state">Checking…</p>
    <div id="outlook-details"></div>
    <button id="outlook-connect">Connect Outlook</button>
  </div>

  <div class="panel" id="whatsapp-panel">
    <h2>WhatsApp</h2>
    <p class="state" id="whatsapp-state">Checking…</p>
    <div id="whatsapp-details"></div>
    <button id="whatsapp-connect">Connect WhatsApp</button>
  </div>

  <div class="panel" id="linkedin-panel">
    <h2>LinkedIn</h2>
    <p class="state" id="linkedin-state">Checking…</p>
    <p>Requires Python installed on your computer — <a href="https://www.python.org/downloads/">get it here</a> if you don't have it.</p>
    <button id="linkedin-connect">Download connection tool</button>
  </div>

<script>
async function pollJSON(url) {
  const resp = await fetch(url);
  return resp.json();
}

function confirmIfConnected(currentStateText, accountLabel) {
  if (currentStateText && currentStateText.toLowerCase().startsWith("connected")) {
    return confirm(`This will disconnect ${accountLabel} — continue?`);
  }
  return true;
}

// --- Outlook ---
document.getElementById("outlook-connect").addEventListener("click", async () => {
  const stateEl = document.getElementById("outlook-state");
  if (!confirmIfConnected(stateEl.textContent, "the connected Outlook account")) return;
  await fetch("/outlook/connect", { method: "POST" });
});

async function refreshOutlook() {
  const data = await pollJSON("/outlook/status");
  const stateEl = document.getElementById("outlook-state");
  const detailsEl = document.getElementById("outlook-details");
  if (data.state === "connected") {
    stateEl.textContent = `Connected as ${data.mailbox}`;
    stateEl.className = "state connected";
    detailsEl.textContent = "";
  } else if (data.state === "pending" || data.state === "starting") {
    stateEl.textContent = "Waiting for you to sign in";
    stateEl.className = "state pending";
    detailsEl.innerHTML = data.code
      ? `Go to <a href="${data.url}" target="_blank">${data.url}</a> and enter code <code class="big">${data.code}</code>`
      : "Starting…";
  } else if (data.state === "expired") {
    stateEl.textContent = "Code expired — click Connect Outlook to get a new one";
    stateEl.className = "state error";
    detailsEl.textContent = "";
  } else {
    stateEl.textContent = "Not connected yet";
    stateEl.className = "state";
    detailsEl.textContent = "";
  }
}

// --- WhatsApp ---
document.getElementById("whatsapp-connect").addEventListener("click", async () => {
  const stateEl = document.getElementById("whatsapp-state");
  if (!confirmIfConnected(stateEl.textContent, "the connected WhatsApp account")) return;
  await fetch("/whatsapp/connect", { method: "POST" });
});

async function refreshWhatsapp() {
  const data = await pollJSON("/whatsapp/status");
  const stateEl = document.getElementById("whatsapp-state");
  const detailsEl = document.getElementById("whatsapp-details");
  if (data.state === "connected") {
    stateEl.textContent = "Connected" + (data.detail ? ` — ${data.detail}` : "");
    stateEl.className = "state connected";
    detailsEl.innerHTML = "";
  } else if (data.state === "qr_pending") {
    stateEl.textContent = "Scan this with your phone's WhatsApp";
    stateEl.className = "state qr_pending";
    detailsEl.innerHTML = `<img id="qr" src="/whatsapp/qr.png?t=${Date.now()}">`;
  } else if (data.state === "logged_out" || data.state === "crashed") {
    stateEl.textContent = data.detail || "Needs attention";
    stateEl.className = `state ${data.state}`;
    detailsEl.textContent = "";
  } else {
    stateEl.textContent = "Not connected yet";
    stateEl.className = "state";
    detailsEl.textContent = "";
  }
}

// --- LinkedIn ---
document.getElementById("linkedin-connect").addEventListener("click", async () => {
  const stateEl = document.getElementById("linkedin-state");
  if (!confirmIfConnected(stateEl.textContent, "the connected LinkedIn account")) return;
  window.location.href = "/linkedin/download-helper";
});

async function refreshLinkedin() {
  const data = await pollJSON("/linkedin/status");
  const stateEl = document.getElementById("linkedin-state");
  stateEl.textContent = data.connected ? "Connected" : "Not connected yet";
  stateEl.className = data.connected ? "state connected" : "state";
}

async function refreshAll() {
  await Promise.all([refreshOutlook(), refreshWhatsapp(), refreshLinkedin()]);
}

refreshAll();
setInterval(refreshAll, 1500);
</script>
</body>
</html>
```

- [ ] **Step 2: Wire the template into a `GET /` route**

Add to `scripts/onboarding/app.py`, near the top imports:

```python
from flask import Flask, jsonify, render_template, send_file
```

(replace the existing `from flask import Flask, jsonify, send_file` line — now includes `render_template`)

Add the route inside `create_app`, before `/status`:

```python
    @flask_app.get("/")
    def index():
        return render_template("index.html")
```

- [ ] **Step 3: Run the app locally and check it renders**

Run: `.venv/Scripts/python.exe scripts/onboarding/app.py`, then open `http://localhost:5000` in a browser.
Expected: three panels render, each showing a real state within 1.5s (not stuck on "Checking…").

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (the new `/` route needs no new test — it's static template rendering, covered by the manual check above)

- [ ] **Step 5: Commit**

```bash
git add scripts/onboarding/templates/index.html scripts/onboarding/app.py
git commit -m "Build the three-panel dashboard page"
```

---

### Task 9: Retire the standalone monitor Task Scheduler entry, update the runbook

**Files:**
- Modify: `runbook.md`

**Interfaces:** none (documentation + one manual infra step)

- [ ] **Step 1: Delete the now-redundant scheduled task**

Run (from an elevated PowerShell, matching `scripts/fix_task_logontype.ps1`'s pattern):
```powershell
Unregister-ScheduledTask -TaskName "CommsPlatformMonitor" -Confirm:$false
```
Expected: no error; `Get-ScheduledTask -TaskName "CommsPlatformMonitor"` now reports it doesn't exist.

- [ ] **Step 2: Document the dashboard in the runbook**

Add a new section to `runbook.md`, after the "Pipeline health monitoring" section:

```markdown
## Ops dashboard (onboarding + live status)

Replaces the standalone `CommsPlatformMonitor` scheduled task —
`scripts/onboarding/app.py` runs the same checks in a background thread
every 15 minutes, whether or not the page is open, alongside a web page
for connecting Outlook/LinkedIn/WhatsApp without the CLI. See
`docs/superpowers/specs/2026-08-31-onboarding-dashboard-design.md` for
the full design.

Run: `python scripts/onboarding/app.py`, then open `http://localhost:5000`.

`ONBOARDING_BASE_URL` (default `http://localhost:5000`) is embedded into
the downloaded LinkedIn helper script so it knows where to upload the
session back to — set this to wherever the dashboard is actually
reachable if it's not on the same machine as whoever's connecting
LinkedIn.

**Where this runs long-term is still an open decision** (see the design
doc's Scope section) — it needs to stay running the same way WhatsApp's
`ingest.js` connector does, so a laptop that gets closed takes the whole
thing down with it.
```

- [ ] **Step 3: Commit**

```bash
git add runbook.md
git commit -m "Document the ops dashboard in the runbook, retire the standalone monitor task"
```

---

## Self-Review Notes

- **Spec coverage:** Problem/merge rationale → Task 3's background thread + Task 9's retirement of the old task. Outlook panel → Task 4. WhatsApp panel → Task 5. LinkedIn panel (local helper, no packaging) → Tasks 6–7. UI copy tone → Task 8's "for your convenience" copy and plain state text. Single-account confirm-before-overwrite → Task 8's `confirmIfConnected`. Data flow (no new store) → every route reads/writes the same existing files, no schema added. Testing → each task has route-level tests with mocked I/O; Task 9 close-the-tab-and-verify-ntfy-still-fires is a manual real-world check, not automatable in this repo's test suite, called out explicitly rather than skipped silently.
- **Placeholder scan:** none found — every step has real, complete code.
- **Type consistency:** `ChannelStatus.channel/healthy/detail` used consistently from Task 1 through Tasks 3–5's JSON shaping. `outlook_client.get_access_token(on_device_code=...)` signature from Task 2 matches its one call site in Task 4. `linkedin_login.STORAGE_STATE_PATH` referenced the same way in Task 7's routes and its tests.
