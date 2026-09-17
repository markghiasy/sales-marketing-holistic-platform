"""Tests for adapters/whatsapp/sync.py's pure-logic functions — no
network, no DB, no Baileys.
"""

from __future__ import annotations

from adapters.whatsapp.sync import _strip_device_suffix, _to_envelope

_SELF_BASE = "61404157396@s.whatsapp.net"
_SELF_WITH_DEVICE = "61404157396:21@s.whatsapp.net"
_CONTACT = "61480619571@s.whatsapp.net"


class TestStripDeviceSuffix:
    def test_strips_device_suffix(self):
        assert _strip_device_suffix(_SELF_WITH_DEVICE) == _SELF_BASE

    def test_leaves_bare_jid_unchanged(self):
        assert _strip_device_suffix(_SELF_BASE) == _SELF_BASE

    def test_leaves_non_whatsapp_style_string_unchanged(self):
        assert _strip_device_suffix("161") == "161"


class TestToEnvelope:
    def _record(self, **overrides) -> dict:
        base = {
            "id": "ABC123",
            "text": "hello",
            "from_me": False,
            "is_group": False,
            "push_name": "Contact Name",
            "timestamp": 1700000000,
            "remote_jid": _CONTACT,
            "participant": None,
        }
        base.update(overrides)
        return base

    def test_drops_record_with_no_text(self):
        assert _to_envelope(self._record(text=None), self_jid=_SELF_WITH_DEVICE) is None

    def test_inbound_direction_and_handles(self):
        env = _to_envelope(self._record(), self_jid=_SELF_WITH_DEVICE)
        assert env is not None
        assert env.direction.value == "inbound"
        assert env.from_handle == _CONTACT
        assert env.to_handles == [_SELF_BASE]  # self_jid's device suffix stripped

    def test_outbound_direction_and_handles(self):
        env = _to_envelope(self._record(from_me=True), self_jid=_SELF_WITH_DEVICE)
        assert env is not None
        assert env.direction.value == "outbound"
        assert env.from_handle == _SELF_BASE  # self_jid's device suffix stripped
        assert env.to_handles == [_CONTACT]

    def test_self_chat_maps_to_the_same_self_identity_regardless_of_device_suffix(self):
        # Real bug found 2026-09-17: a "Message Yourself" chat's
        # remote_jid is always the bare form, but self_jid (from
        # self_jid.txt) carries whatever device suffix was current at
        # connect time — different across reconnects. Before stripping
        # both to the same bare form, these never string-compared equal,
        # so every self-chat message created a phantom "unknown contact"
        # identity for your own bare number instead of resolving to self.
        env = _to_envelope(
            self._record(from_me=True, remote_jid=_SELF_BASE),
            self_jid=_SELF_WITH_DEVICE,
        )
        assert env is not None
        assert env.from_handle == _SELF_BASE
        assert env.to_handles == [_SELF_BASE]

    def test_group_outbound_has_no_to_handles(self):
        env = _to_envelope(
            self._record(from_me=True, is_group=True, remote_jid="123456-789@g.us"),
            self_jid=_SELF_WITH_DEVICE,
        )
        assert env is not None
        assert env.to_handles == []

    def test_group_inbound_uses_participant_as_sender(self):
        env = _to_envelope(
            self._record(is_group=True, remote_jid="123456-789@g.us", participant=_SELF_WITH_DEVICE),
            self_jid=_SELF_WITH_DEVICE,
        )
        assert env is not None
        assert env.from_handle == _SELF_BASE  # participant's device suffix stripped too
