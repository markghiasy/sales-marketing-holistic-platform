"""Shared browser launch for every LinkedIn script (client.py, login.py,
export_sync.py, request_export.py) — one place for the anti-detection
posture Mark ratified in writing on 2026-08-28: no fingerprint or
countermeasure work, ever — pacing and the daily session cap (§13) ARE
the strategy. If that stops being sufficient, the answer is to stop and
talk, not escalate technique.

Superseded 2026-08-28: an earlier version of this file (built off a
verbal "make it more human" approval on the call) patched
navigator.webdriver/plugins/languages and stripped "Headless" from the
User-Agent string. Removed once Mark's written follow-up clarified that
was exactly the kind of active spoofing he meant to rule out.

What this still does: launches the real, locally-installed Chrome
(`channel="chrome"`) instead of Playwright's bundled Chromium, and sets
a realistic viewport. Neither of those falsifies anything the browser
reports — they're a choice of which real browser and window size to
use, not a fabricated signal. A `headless=True` run still self-reports
"HeadlessChrome" in its own User-Agent, left as-is on purpose.
"""

from __future__ import annotations

from playwright.sync_api import Browser, BrowserContext, Playwright

# a real, current desktop viewport — not Playwright's default 1280x720
_VIEWPORT = {"width": 1536, "height": 864}


def launch_browser_context(
    p: Playwright, headless: bool = True, storage_state: str | None = None
) -> tuple[Browser, BrowserContext]:
    browser = p.chromium.launch(channel="chrome", headless=headless)
    context = browser.new_context(storage_state=storage_state, viewport=_VIEWPORT)
    return browser, context
