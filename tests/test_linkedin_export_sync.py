from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from adapters.linkedin.export_sync import (
    _connection_id,
    _handle,
    _parse_connected_on,
    _parse_connections_csv,
    _to_envelope,
)


class TestHandle:
    def test_prefers_profile_url(self):
        assert _handle("Jane Doe", "https://www.linkedin.com/in/janedoe") == (
            "https://www.linkedin.com/in/janedoe"
        )

    def test_lowercases_url(self):
        assert _handle("Jane", "HTTPS://WWW.LINKEDIN.COM/IN/JANE") == "https://www.linkedin.com/in/jane"

    def test_falls_back_to_name_prefixed_handle(self):
        assert _handle("Jane Doe", "") == "name:jane doe"


class TestConnectionId:
    def test_prefers_profile_url(self):
        assert _connection_id("Jane Doe", "https://www.linkedin.com/in/janedoe") == (
            "https://www.linkedin.com/in/janedoe"
        )

    def test_falls_back_to_name(self):
        assert _connection_id("Jane Doe", "") == "name:jane doe"

    def test_blank_rows_collide_by_design(self):
        # documented real behaviour, not accidental: 14 of 935 real rows
        # in the 2026-08-28 archive were completely blank (deactivated
        # accounts) and all collapsed to the same id — there's nothing
        # to distinguish them by, so this is correct, not a bug
        assert _connection_id("", "") == _connection_id("", "")


class TestParseConnectedOn:
    def test_parses_real_format(self):
        # confirmed real format 2026-08-28: "20 Aug 2026"
        assert _parse_connected_on("20 Aug 2026") == date(2026, 8, 20)

    def test_returns_none_for_empty_string(self):
        assert _parse_connected_on("") is None

    def test_returns_none_for_unparseable_string(self):
        assert _parse_connected_on("not a date") is None


class TestParseConnectionsCsv:
    def _make_zip(self, connections_csv_content: str) -> Path:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Connections.csv", connections_csv_content)
        path = Path("test_connections_archive.zip")
        path.write_bytes(buf.getvalue())
        return path

    def test_skips_real_privacy_preamble(self, tmp_path, monkeypatch):
        # real Connections.csv has a 3-line preamble before the header —
        # confirmed 2026-08-28 against a real archive
        monkeypatch.chdir(tmp_path)
        content = (
            "Notes:\n"
            '"When exporting your connection data..."\n'
            "\n"
            "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
            "Jane,Doe,https://www.linkedin.com/in/janedoe,,Acme Corp,Engineer,20 Aug 2026\n"
        )
        zip_path = self._make_zip(content)
        rows = _parse_connections_csv(zip_path)
        assert len(rows) == 1
        assert rows[0]["first name"] == "Jane"
        assert rows[0]["company"] == "Acme Corp"

    def test_raises_when_header_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        zip_path = self._make_zip("some,unexpected,format\n")
        with pytest.raises(RuntimeError, match="couldn't find"):
            _parse_connections_csv(zip_path)


class TestToEnvelope:
    _SELF_URL = "https://www.linkedin.com/in/evang2"

    def _row(self, **overrides) -> dict:
        base = {
            "conversation id": "conv1",
            "content": "Hello there",
            "from": "Jane Doe",
            "sender profile url": "https://www.linkedin.com/in/janedoe",
            "to": "Eva Ng",
            "recipient profile urls": self._SELF_URL,
            "date": "2026-08-20 05:33:12 UTC",
        }
        base.update(overrides)
        return base

    def test_drops_row_with_no_content(self):
        assert _to_envelope(self._row(content=""), self._SELF_URL) is None

    def test_direction_inbound_from_other_party(self):
        env = _to_envelope(self._row(), self._SELF_URL)
        assert env is not None
        assert env.direction.value == "inbound"

    def test_direction_outbound_from_self(self):
        row = self._row(
            **{
                "from": "Eva Ng",
                "sender profile url": self._SELF_URL,
                "to": "Jane Doe",
                "recipient profile urls": "https://www.linkedin.com/in/janedoe",
            }
        )
        env = _to_envelope(row, self._SELF_URL)
        assert env is not None
        assert env.direction.value == "outbound"

    def test_parses_non_iso_date_format(self):
        # real confirmed format: "2026-08-20 05:33:12 UTC", not ISO 8601
        env = _to_envelope(self._row(), self._SELF_URL)
        assert env is not None
        assert env.sent_at.year == 2026
        assert env.sent_at.month == 8
        assert env.sent_at.day == 20
