"""Tests for adapters/outlook/sync.py's pure-logic functions — no network,
no DB. Quote-stripping fixtures are shaped like real HTML bodies found in
this mailbox on 2026-08-28 (see runbook.md), not invented from scratch,
since the exact-match-vs-substring-match bug that shipped once already
came from not checking real markup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from adapters.outlook.sync import _resolve_sent_at, _strip_html, _to_envelope


class TestStripHtml:
    def test_plain_text_passthrough(self):
        body = {"contentType": "text", "content": "Hello, this is plain text."}
        assert _strip_html(body) == "Hello, this is plain text."

    def test_html_tags_removed(self):
        # each tag becomes a literal space (see _TAG_RE.sub), so adjacent
        # tags produce a double space in the middle — real, existing
        # behaviour, not something this test is asserting should change
        body = {"contentType": "html", "content": "<p>Hello <b>world</b></p>"}
        assert _strip_html(body) == "Hello  world"

    def test_html_entities_unescaped(self):
        body = {"contentType": "html", "content": "<p>Tom &amp; Jerry &lt;3</p>"}
        assert _strip_html(body) == "Tom & Jerry <3"

    def test_strips_gmail_quote_with_second_class(self):
        # real shape: class="gmail_quote gmail_quote_container" — the
        # bug that shipped once matched only the exact single-class form
        body = {
            "contentType": "html",
            "content": (
                "<div>Thanks, see you then!</div>"
                '<div class="gmail_quote gmail_quote_container">'
                "<div>On Mon, 11 Nov 2024, Jane wrote:</div>"
                "<div>Here is the original long message that should be cut.</div>"
                "</div>"
            ),
        }
        result = _strip_html(body)
        assert "Thanks, see you then!" in result
        assert "original long message" not in result

    def test_strips_prefixed_gmail_quote_class(self):
        # real shape: class="x_gmail_quote" — a different real variant
        body = {
            "contentType": "html",
            "content": (
                "<div>My reply</div>"
                '<div class="x_gmail_quote"><div>quoted history here</div></div>'
            ),
        }
        result = _strip_html(body)
        assert "My reply" in result
        assert "quoted history" not in result

    def test_strips_outlook_reply_marker(self):
        body = {
            "contentType": "html",
            "content": (
                "<div>New reply text</div>"
                '<div id="divRplyFwdMsg">From: someone@example.com</div>'
            ),
        }
        result = _strip_html(body)
        assert "New reply text" in result
        assert "someone@example.com" not in result

    def test_strips_bare_blockquote(self):
        body = {
            "contentType": "html",
            "content": "<div>My comment</div><blockquote>Old quoted text</blockquote>",
        }
        result = _strip_html(body)
        assert "My comment" in result
        assert "Old quoted text" not in result

    def test_plain_text_wrote_marker_stripped(self):
        body = {
            "contentType": "text",
            "content": "Sounds good!\nOn Mon, 11 Nov 2024, 11:58 am Jane wrote:\n> original text",
        }
        result = _strip_html(body)
        assert result == "Sounds good!"

    def test_no_quote_marker_returns_full_body(self):
        body = {"contentType": "html", "content": "<p>Just a normal message, nothing quoted.</p>"}
        assert _strip_html(body) == "Just a normal message, nothing quoted."


class TestResolveSentAt:
    def test_prefers_date_header_over_received_date_time(self):
        # the actual bug this exists for: New Outlook's .eml importer
        # stamps receivedDateTime with import time, not the real date
        raw = {
            "receivedDateTime": "2026-08-27T12:00:00Z",
            "internetMessageHeaders": [
                {"name": "Date", "value": "Mon, 11 Nov 2024 11:58:00 +0000"},
            ],
        }
        result = _resolve_sent_at(raw)
        assert result.year == 2024
        assert result.month == 11
        assert result.day == 11

    def test_falls_back_to_received_date_time_when_no_date_header(self):
        raw = {"receivedDateTime": "2026-08-27T12:00:00+00:00", "internetMessageHeaders": []}
        result = _resolve_sent_at(raw)
        assert result == datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

    def test_falls_back_on_malformed_date_header(self):
        raw = {
            "receivedDateTime": "2026-08-27T12:00:00+00:00",
            "internetMessageHeaders": [{"name": "Date", "value": "not a real date"}],
        }
        result = _resolve_sent_at(raw)
        assert result == datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


class TestToEnvelope:
    _BASE_RAW: ClassVar[dict] = {
        "internetMessageId": "<msg1@example.com>",
        "conversationId": "conv1",
        "from": {"emailAddress": {"address": "Sender@Example.com", "name": "Sender Name"}},
        "toRecipients": [{"emailAddress": {"address": "Me@Example.com", "name": "Me"}}],
        "receivedDateTime": "2026-08-27T12:00:00Z",
        "internetMessageHeaders": [],
        "subject": "Hello",
        "body": {"contentType": "text", "content": "Hi there"},
        "inferenceClassification": "focused",
    }

    def test_drops_message_with_no_internet_message_id(self):
        raw = dict(self._BASE_RAW, internetMessageId=None)
        assert _to_envelope(raw, self_handles={"me@example.com"}) is None

    def test_direction_inbound_when_sender_not_self(self):
        env = _to_envelope(self._BASE_RAW, self_handles={"me@example.com"})
        assert env is not None
        assert env.direction.value == "inbound"
        assert env.from_handle == "sender@example.com"  # lowercased

    def test_direction_outbound_when_sender_is_self(self):
        env = _to_envelope(self._BASE_RAW, self_handles={"sender@example.com"})
        assert env is not None
        assert env.direction.value == "outbound"

    def test_is_automated_true_for_other_classification(self):
        raw = dict(self._BASE_RAW, inferenceClassification="other")
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_false_for_focused_classification(self):
        env = _to_envelope(self._BASE_RAW, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is False
