"""Trigger LinkedIn's official "Download my data" archive request.

This replaces the network-interception / DOM-scraping approach in
client.py as the primary way to get LinkedIn messages: it's LinkedIn's own
self-service data-export feature (Settings > Data Privacy > Get a copy of
your data), not automation of the messaging UI, so it doesn't carry the
same ToS-grey / detection risk §13 flags for scraping. Confirmed live on
2026-08-19: selecting "Download larger data archive" (not the "select
specific files" quick option — Messages isn't offered there) and
submitting shows "Your request... was made on <date>. We will send you an
email when your download is ready" with a ~24h turnaround.

This only requests the archive. `export_sync.py` checks whether one has
finished processing and, if so, downloads and ingests it — LinkedIn
doesn't expose a webhook or push notification we can drive off of, so this
has to be two separate runs on a schedule, not one script that waits.

Run: python -m adapters.linkedin.request_export
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = Path(__file__).parent / ".storage_state.json"
DATA_PRIVACY_URL = "https://www.linkedin.com/mypreferences/d/download-my-data"


def request_export(headless: bool = True) -> str:
    """Returns 'requested', 'already_pending', or raises if the page
    doesn't look like what was captured on 2026-08-19 — fail loudly rather
    than silently doing nothing if LinkedIn changes this flow."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()
        page.goto(DATA_PRIVACY_URL)
        page.wait_for_load_state("networkidle")

        if page.query_selector("text=Request pending"):
            browser.close()
            return "already_pending"

        full_archive_radio = page.query_selector(
            'input[type="radio"] >> nth=0'
        ) or page.get_by_text("Download larger data archive").first

        if full_archive_radio is None:
            browser.close()
            raise RuntimeError(
                "couldn't find the 'Download larger data archive' option — "
                "LinkedIn may have changed this page since 2026-08-19"
            )
        full_archive_radio.click()

        request_button = page.get_by_role("button", name="Request archive")
        request_button.click()

        page.wait_for_selector("text=Request pending", timeout=15_000)
        browser.close()
        return "requested"


if __name__ == "__main__":
    result = request_export(headless=True)
    print(result)
