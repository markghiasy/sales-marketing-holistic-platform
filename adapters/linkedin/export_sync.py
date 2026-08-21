"""Check whether a requested LinkedIn data archive is ready; if so,
download it, parse messages.csv, and upsert into the store. Safe to run
on a schedule (daily/hourly, whatever the eventual cadence is) — if
nothing's ready yet, this is a clean no-op, not an error.

Run: python -m adapters.linkedin.export_sync

Verified against a real archive on 2026-08-21 (`Basic_LinkedInDataExport_
08-20-2026.zip.zip`, requested 2026-08-19, 1,464 real messages). Two things
the earlier guessed version got wrong, fixed here:
- The on-screen "ready for download" list only names 5 categories
  (Articles, Invitations, Profile, Recommendations, Registration) but the
  actual zip has 34 files including `messages.csv`, `Connections.csv`,
  etc. — that on-screen list is not the real manifest, don't trust it.
- The zip also contains `learning_role_play_messages.csv`,
  `learning_coach_messages.csv`, and `guide_messages.csv` — all of which
  end in "messages.csv" too, and `learning_role_play_messages.csv` sorts
  before the real `messages.csv` in the archive listing. Matching on
  `endswith("messages.csv")` picked the wrong file entirely.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from ..envelope import Channel, Direction, Envelope
from ..store_writer import upsert

STORAGE_STATE_PATH = Path(__file__).parent / ".storage_state.json"
DATA_PRIVACY_URL = "https://www.linkedin.com/mypreferences/d/download-my-data"
DOWNLOAD_DIR = Path(__file__).parent / ".downloads"

# Confirmed real header (2026-08-21): CONVERSATION ID, CONVERSATION TITLE,
# FROM, SENDER PROFILE URL, TO, RECIPIENT PROFILE URLS, DATE, SUBJECT,
# CONTENT, FOLDER, ATTACHMENTS. Matched case-insensitively below.
_EXPECTED_COLUMNS = {
    "conversation id", "from", "sender profile url", "to",
    "recipient profile urls", "date", "content",
}


def _download_archive(headless: bool = True) -> Path | None:
    """Returns the path to a downloaded zip, or None if nothing's ready."""
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()
        page.goto(DATA_PRIVACY_URL)
        page.wait_for_load_state("networkidle")

        download_link = page.get_by_role("link", name="Download archive").first
        if download_link.count() == 0:
            browser.close()
            return None  # still pending, or nothing requested yet

        with page.expect_download() as download_info:
            download_link.click()
        download = download_info.value

        out_path = DOWNLOAD_DIR / download.suggested_filename
        download.save_as(str(out_path))
        browser.close()
        return out_path


def _parse_messages_csv(zip_path: Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as zf:
        # exact filename match — the archive also ships
        # learning_role_play_messages.csv / learning_coach_messages.csv /
        # guide_messages.csv, which an endswith() match would catch too
        # (and did, in an earlier version of this function: see module
        # docstring)
        csv_names = [n for n in zf.namelist() if n.lower() == "messages.csv"]
        if not csv_names:
            raise RuntimeError(
                f"no messages.csv in archive — found: {zf.namelist()[:20]}"
            )
        raw = zf.read(csv_names[0]).decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(raw))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = _EXPECTED_COLUMNS - headers
    if missing:
        raise RuntimeError(
            f"messages.csv is missing expected columns {missing} — actual "
            f"headers: {reader.fieldnames}. Update _EXPECTED_COLUMNS and the "
            f"row-mapping in _to_envelope below to match."
        )

    # normalise keys to lowercase so the rest of this module doesn't care
    # which capitalisation LinkedIn shipped this export with
    return [{k.strip().lower(): v for k, v in row.items()} for row in reader]


def _parse_export_date(date_str: str) -> datetime:
    # real format confirmed 2026-08-21: "2026-08-20 05:33:12 UTC" — not
    # ISO 8601, fromisoformat() rejects the trailing " UTC" outright
    if date_str.endswith(" UTC"):
        naive = datetime.strptime(date_str[: -len(" UTC")], "%Y-%m-%d %H:%M:%S")
        return naive.replace(tzinfo=UTC)
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def _handle(name: str, profile_url: str) -> str:
    # prefer the real profile URL — stable, and doesn't collide across
    # people who happen to share a display name. Fall back to a name-
    # prefixed handle (so it's visibly distinct from a URL in the
    # identity table, not silently mixed with real ones) only when
    # LinkedIn didn't give us a URL for this row.
    profile_url = profile_url.strip()
    if profile_url:
        return profile_url.lower()
    return f"name:{name.strip().lower()}"


def _to_envelope(row: dict, self_profile_url: str) -> Envelope | None:
    conversation_id = row.get("conversation id", "").strip()
    content = row.get("content", "").strip()
    if not conversation_id or not content:
        return None

    from_name = row.get("from", "").strip()
    from_handle = _handle(from_name, row.get("sender profile url", ""))
    to_name = row.get("to", "").strip()
    # RECIPIENT PROFILE URLS is plural — comma-separated for group threads,
    # same order as the (also comma-separated) TO name field
    to_names = [n.strip() for n in to_name.split(",")] if to_name else []
    to_urls = [
        u.strip() for u in row.get("recipient profile urls", "").split(",")
    ] if row.get("recipient profile urls") else []
    to_handles = [
        _handle(n, to_urls[i] if i < len(to_urls) else "")
        for i, n in enumerate(to_names)
    ]

    direction = (
        Direction.outbound if from_handle == self_profile_url.lower() else Direction.inbound
    )

    date_str = row.get("date", "").strip()
    try:
        sent_at = _parse_export_date(date_str)
    except ValueError:
        sent_at = datetime.now(UTC)  # unparseable date — shouldn't happen
                                      # against the confirmed format above,
                                      # kept as a last-resort fallback

    # date_str is only second-precision ("2026-08-20 05:33:12 UTC") — two
    # different messages from the same person in the same thread within
    # the same second would collide on conversation+time+sender alone and
    # the second one would be silently dropped as a "duplicate". A short
    # content hash makes that collision require identical text too, not
    # just identical timing.
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

    return Envelope(
        channel=Channel.linkedin,
        external_id=f"{conversation_id}:{date_str}:{from_handle}:{content_hash}",
        thread_external_id=conversation_id,
        direction=direction,
        sent_at=sent_at,
        from_handle=from_handle,
        to_handles=to_handles,
        from_display_name=from_name or None,
        to_display_names=to_names,
        subject=None,
        body_text=content,
        is_group=len(to_handles) > 1,
        is_automated=False,
        raw=row,
    )


def run() -> None:
    load_dotenv()
    self_profile_url = os.environ["LINKEDIN_SELF_PROFILE_URL"]  # e.g.
        # "https://www.linkedin.com/in/evang2" — matched against the CSV's
        # SENDER/RECIPIENT PROFILE URL columns to determine direction

    zip_path = _download_archive(headless=True)
    if zip_path is None:
        print("no archive ready yet")  # noqa: T201
        return

    rows = _parse_messages_csv(zip_path)

    count = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for row in rows:
            env = _to_envelope(row, self_profile_url)
            if env is None:
                continue
            upsert(conn, env, self_profile_url.lower())
            conn.commit()
            count += 1

    print(f"synced {count} messages from {zip_path.name}")  # noqa: T201


if __name__ == "__main__":
    run()
