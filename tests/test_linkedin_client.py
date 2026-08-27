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
    _to_envelope,
)

_SELF_URN = "urn:li:fsd_profile:ACoAADhUQ4oBrW66erO7cZeDChU1SUc-o9uKrcA"
_SENDER_URN = "urn:li:fsd_profile:ACoAAG1CyvMBp8I9emeKkImcQK0x41MFBKOxsNo"
_CONVERSATION_URN = f"urn:li:msg_conversation:({_SELF_URN},2-OTgwNzRmZGUtYjQ2Yy00NGYzLWFkZmEtNmU5YWNmZTg2NTg0XzEwMA==)"


def _real_shaped_response(text: str = "Hello") -> dict:
    return {
        "data": {
            "messengerMessagesBySyncToken": {
                "elements": [
                    {
                        "entityUrn": "urn:li:msg_message:(x,2-abc)",
                        "body": {"text": text},
                        "sender": {"hostIdentityUrn": _SENDER_URN},
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
