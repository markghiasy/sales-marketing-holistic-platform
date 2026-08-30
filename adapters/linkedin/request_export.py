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

Re-verified 2026-08-28 requesting a fresh archive: the option-selection
logic broke since 2026-08-19 in two ways, both fixed — LinkedIn's own
`<label>` around the radio button now intercepts direct clicks on it, and
the option was being picked by DOM position rather than its label text
(fragile: would silently request the wrong archive if the two options
ever got reordered). See the fix comments below for both.

Run: python -m adapters.linkedin.request_export
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from .browser import launch_browser_context

STORAGE_STATE_PATH = Path(__file__).parent / ".storage_state.json"
DATA_PRIVACY_URL = "https://www.linkedin.com/mypreferences/d/download-my-data"


def request_export(headless: bool = True) -> str:
    """Returns 'requested', 'already_pending', or raises if the page
    doesn't look like what was captured on 2026-08-19 — fail loudly rather
    than silently doing nothing if LinkedIn changes this flow."""
    with sync_playwright() as p:
        browser, context = launch_browser_context(
            p, headless=headless, storage_state=str(STORAGE_STATE_PATH)
        )
        page = context.new_page()
        page.goto(DATA_PRIVACY_URL)
        page.wait_for_load_state("networkidle")

        if page.query_selector("text=Request pending"):
            browser.close()
            return "already_pending"

        # Match by the label's own text ("...including connections,
        # verifications, contacts...") instead of position — an earlier
        # version picked whichever <input type="radio"> happened to be
        # first in the DOM, which only worked by coincidence of today's
        # ordering. If LinkedIn ever swaps the two options' order, a
        # position-based selector would silently request the *wrong*
        # archive (missing Connections.csv) with no error at all — found
        # while fixing a separate, unrelated click-interception bug
        # (2026-08-28) and worth fixing properly rather than patching
        # around the symptom.
        full_archive_label = None
        for label in page.query_selector_all("label"):
            if "connections" in label.inner_text().lower():
                full_archive_label = label
                break

        if full_archive_label is None:
            browser.close()
            raise RuntimeError(
                "couldn't find a data-archive option whose label mentions "
                "'connections' — LinkedIn may have changed this page's "
                "wording or structure since 2026-08-28"
            )
        # the radio's own <label> visually wraps it and intercepts pointer
        # events on the <input> directly — found 2026-08-28. Clicking the
        # label itself (same toggle behaviour via its `for` attribute)
        # sidesteps that rather than forcing a click through it.
        full_archive_label.click()

        request_button = page.get_by_role("button", name="Request archive")
        request_button.click()

        page.wait_for_selector("text=Request pending", timeout=15_000)
        browser.close()
        return "requested"


if __name__ == "__main__":
    result = request_export(headless=True)
    print(result)
