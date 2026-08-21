"""One-time interactive login. Opens a real, visible browser window; you log
in by hand (credentials, 2FA, whatever LinkedIn asks for — nothing here ever
sees or touches your password). Once you land on the feed, the session is
saved to disk and every later run reuses it headless.

Run: python -m adapters.linkedin.login
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = Path(__file__).parent / ".storage_state.json"


def login() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        print("Log in in the browser window. Waiting for the feed to load...")
        page.wait_for_url("https://www.linkedin.com/feed/**", timeout=300_000)

        context.storage_state(path=str(STORAGE_STATE_PATH))
        print(f"Session saved to {STORAGE_STATE_PATH}")
        browser.close()


if __name__ == "__main__":
    login()
