from __future__ import annotations

from adapters.outlook.contacts_sync import _normalise_phone, _to_row


class TestNormalisePhone:
    def test_strips_plus_spaces_and_parens(self):
        assert _normalise_phone("+1 (580) 670-9090") == "15806709090"

    def test_digits_only_passthrough(self):
        assert _normalise_phone("15806709090") == "15806709090"

    def test_matches_whatsapp_jid_numeric_part(self):
        # the whole point of this normalisation — real WhatsApp identity
        # handles look like "15806709090@s.whatsapp.net"
        jid = "15806709090@s.whatsapp.net"
        phone_number_part = jid.split("@")[0]
        assert _normalise_phone("+1 (580) 670-9090") == phone_number_part


class TestToRow:
    def test_extracts_and_normalises_email_and_phone(self):
        raw = {
            "id": "contact-1",
            "displayName": "Jane Doe",
            "emailAddresses": [{"address": "Jane@Example.com"}],
            "mobilePhone": "+1 (580) 670-9090",
            "businessPhones": [],
            "homePhones": [],
        }
        contact_id, display_name, emails, phones = _to_row(raw)
        assert contact_id == "contact-1"
        assert display_name == "Jane Doe"
        assert emails == ["jane@example.com"]
        assert phones == ["15806709090"]

    def test_handles_missing_display_name(self):
        raw = {"id": "contact-2", "emailAddresses": [], "businessPhones": [], "homePhones": []}
        _, display_name, emails, phones = _to_row(raw)
        assert display_name is None
        assert emails == []
        assert phones == []

    def test_combines_multiple_phone_fields(self):
        raw = {
            "id": "contact-3",
            "mobilePhone": "5551234567",
            "businessPhones": ["5559876543"],
            "homePhones": ["5551112222"],
            "emailAddresses": [],
        }
        _, _, _, phones = _to_row(raw)
        assert phones == ["5551234567", "5559876543", "5551112222"]

    def test_skips_null_mobile_phone(self):
        # mobilePhone is a single field (not a list), so it can be None —
        # the None must not leak into the phones list as a literal value
        raw = {
            "id": "contact-4",
            "mobilePhone": None,
            "businessPhones": ["5559876543"],
            "homePhones": [],
            "emailAddresses": [],
        }
        _, _, _, phones = _to_row(raw)
        assert phones == ["5559876543"]
