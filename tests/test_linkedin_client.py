"""Tests for adapters/linkedin/client.py's pure-logic functions.
_extract_messages' fixture is the real response shape captured against a
live message on 2026-08-28 (see runbook.md) — the whole reason this file
exists is that the previously-guessed shape was wrong in three separate
ways, so these fixtures are deliberately not idealised/simplified.
"""

from __future__ import annotations

from adapters.linkedin.client import (
    _extract_messages,
    _self_urn_from_conversation_urn,
    _sender_name,
    _to_envelope,
)

_SELF_URN = "urn:li:fsd_profile:ACoAADhUQ4oBrW66erO7cZeDChU1SUc-o9uKrcA"
_SENDER_URN = "urn:li:fsd_profile:ACoAAG1CyvMBp8I9emeKkImcQK0x41MFBKOxsNo"
_CONVERSATION_URN = f"urn:li:msg_conversation:({_SELF_URN},2-OTgwNzRmZGUtYjQ2Yy00NGYzLWFkZmEtNmU5YWNmZTg2NTg0XzEwMA==)"


def _real_shaped_response(text: str = "Hello", sender_name: dict | None = None) -> dict:
    sender = {"hostIdentityUrn": _SENDER_URN}
    if sender_name is not None:
        sender["participantType"] = sender_name
    return {
        "data": {
            "messengerMessagesBySyncToken": {
                "elements": [
                    {
                        "entityUrn": "urn:li:msg_message:(x,2-abc)",
                        "body": {"text": text},
                        "sender": sender,
                        "conversation": {"entityUrn": _CONVERSATION_URN},
                        "deliveredAt": 1787864586773,
                    }
                ]
            }
        }
    }


class TestSelfUrnFromConversationUrn:
    def test_extracts_first_component(self):
        assert _self_urn_from_conversation_urn(_CONVERSATION_URN) == _SELF_URN

    def test_returns_none_for_unrecognised_shape(self):
        assert _self_urn_from_conversation_urn("not a conversation urn") is None

    def test_returns_none_for_empty_string(self):
        assert _self_urn_from_conversation_urn("") is None


class TestSenderName:
    # Real shape captured live 2026-09-17 (see runbook.md) — this is
    # exactly why _extract_messages() never captured a display name
    # before now: the name is nested two levels deep as {"text": "..."}
    # AttributedText objects, not a plain string anywhere on `sender`.
    def test_extracts_member_full_name(self):
        sender = {
            "hostIdentityUrn": _SENDER_URN,
            "participantType": {
                "member": {
                    "firstName": {"text": "Amber"},
                    "lastName": {"text": "Main"},
                },
                "organization": None,
                "agent": None,
            },
        }
        assert _sender_name(sender) == "Amber Main"

    def test_extracts_organization_name_when_no_member(self):
        sender = {
            "hostIdentityUrn": "urn:li:fsd_company:1115",
            "participantType": {
                "member": None,
                "organization": {"name": {"text": "SAP"}},
                "agent": None,
            },
        }
        assert _sender_name(sender) == "SAP"

    def test_returns_none_when_no_name_data_at_all(self):
        assert _sender_name({}) is None
        assert _sender_name({"participantType": {}}) is None
        assert _sender_name({"participantType": {"member": {}}}) is None


class TestExtractMessages:
    def test_extracts_from_real_shaped_response(self):
        messages = _extract_messages(_real_shaped_response("你好"))
        assert len(messages) == 1
        msg = messages[0]
        assert msg["body_text"] == "你好"
        assert msg["sender_urn"] == _SENDER_URN
        assert msg["conversation_urn"] == _CONVERSATION_URN
        assert msg["created_at_ms"] == 1787864586773

    def test_ignores_response_with_no_elements(self):
        payload = {"data": {"messengerMessagesBySyncToken": {"elements": []}}}
        assert _extract_messages(payload) == []

    def test_ignores_unrelated_response_shape(self):
        # e.g. a presenceStatusTopic or some other non-message response
        # on the same page — must not raise, just yield nothing
        assert _extract_messages({"data": {}}) == []
        assert _extract_messages({}) == []

    def test_skips_message_with_no_text(self):
        payload = _real_shaped_response()
        payload["data"]["messengerMessagesBySyncToken"]["elements"][0]["body"] = {}
        assert _extract_messages(payload) == []

    def test_carries_sender_name_through(self):
        payload = _real_shaped_response(sender_name={
            "member": {"firstName": {"text": "Amber"}, "lastName": {"text": "Main"}},
        })
        messages = _extract_messages(payload)
        assert messages[0]["sender_name"] == "Amber Main"

    def test_sender_name_none_when_absent(self):
        messages = _extract_messages(_real_shaped_response())
        assert messages[0]["sender_name"] is None


class TestToEnvelope:
    def _raw(self, sender_urn: str = _SENDER_URN) -> dict:
        return {
            "message_urn": "urn:li:msg_message:(x,2-abc)",
            "conversation_urn": _CONVERSATION_URN,
            "body_text": "Hello",
            "sender_urn": sender_urn,
            "created_at_ms": 1787864586773,
            "thread_id": _CONVERSATION_URN,
        }

    def test_drops_message_with_no_message_urn(self):
        raw = self._raw()
        raw["message_urn"] = ""
        assert _to_envelope(raw) is None

    def test_drops_message_with_unparseable_conversation_urn(self):
        raw = self._raw()
        raw["conversation_urn"] = "garbage"
        assert _to_envelope(raw) is None

    def test_direction_inbound_when_sender_is_other_party(self):
        env = _to_envelope(self._raw(sender_urn=_SENDER_URN))
        assert env is not None
        assert env.direction.value == "inbound"
        assert env.from_handle == _SENDER_URN
        assert env.to_handles == [_SELF_URN]

    def test_direction_outbound_when_sender_is_self(self):
        env = _to_envelope(self._raw(sender_urn=_SELF_URN))
        assert env is not None
        assert env.direction.value == "outbound"
        assert env.to_handles == []

    def test_inbound_carries_sender_name_as_display_name(self):
        raw = self._raw(sender_urn=_SENDER_URN)
        raw["sender_name"] = "Amber Main"
        env = _to_envelope(raw)
        assert env is not None
        assert env.direction.value == "inbound"
        assert env.from_display_name == "Amber Main"

    def test_outbound_never_carries_sender_name_as_display_name(self):
        # an outbound message's own sender_name (if ever present) would
        # describe the self identity, not the contact — must not leak in
        raw = self._raw(sender_urn=_SELF_URN)
        raw["sender_name"] = "Eva Ng"
        env = _to_envelope(raw)
        assert env is not None
        assert env.direction.value == "outbound"
        assert env.from_display_name is None

    def test_outbound_uses_other_participant_urn_when_present(self):
        # Regression test for a real bug found 2026-09-17: an outbound
        # message's recipient was never recorded (to_handles always []),
        # so message_participant never got a 'to' edge for the contact on
        # your own replies — the triage inbox's thread reconstruction
        # silently dropped every message you sent. fetch_conversations()
        # now backfills other_participant_urn from an inbound message
        # already seen in the same thread; _to_envelope must use it.
        raw = self._raw(sender_urn=_SELF_URN)
        raw["other_participant_urn"] = _SENDER_URN
        env = _to_envelope(raw)
        assert env is not None
        assert env.direction.value == "outbound"
        assert env.to_handles == [_SENDER_URN]
