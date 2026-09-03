# tests/test_resolution_run.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from adapters.resolution.run import run


def test_run_calls_every_rule_and_structured_facts(monkeypatch):
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_cursor = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

    with patch("adapters.resolution.run.psycopg.connect", return_value=fake_conn), \
         patch("adapters.resolution.run.rule_exact_email_match", return_value=0) as m1, \
         patch("adapters.resolution.run.rule_contact_bridge", return_value=0) as m2, \
         patch("adapters.resolution.run.rule_signature_phone", return_value=0) as m3, \
         patch("adapters.resolution.run.rule_linkedin_correlation", return_value=0) as m4, \
         patch("adapters.resolution.run.extract_structured_facts", return_value=0) as m5, \
         patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
        run()

    m1.assert_called_once()
    m2.assert_called_once()
    m3.assert_called_once()
    m4.assert_called_once()
    m5.assert_called_once()


def test_run_survives_one_rule_raising(monkeypatch, capsys):
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_cursor = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

    with patch("adapters.resolution.run.psycopg.connect", return_value=fake_conn), \
         patch("adapters.resolution.run.rule_exact_email_match", side_effect=RuntimeError("boom")), \
         patch("adapters.resolution.run.rule_contact_bridge", return_value=0) as m2, \
         patch("adapters.resolution.run.rule_signature_phone", return_value=0), \
         patch("adapters.resolution.run.rule_linkedin_correlation", return_value=0), \
         patch("adapters.resolution.run.extract_structured_facts", return_value=0), \
         patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
        run()  # must not raise

    m2.assert_called_once()  # the rule after the failing one still ran
    assert "boom" in capsys.readouterr().err
