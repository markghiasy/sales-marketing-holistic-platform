"""Tests for adapters/outlook/sync.py's pure-logic functions — no network,
no DB. Quote-stripping fixtures are shaped like real HTML bodies found in
this mailbox on 2026-08-28 (see runbook.md), not invented from scratch,
since the exact-match-vs-substring-match bug that shipped once already
came from not checking real markup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from adapters.outlook.sync import _resolve_sent_at, _strip_html, _to_envelope, is_automated


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

    def test_strips_gmail_signature_block_via_data_smartmail_marker(self):
        # real shape (2026-09-17): a corrupted nested tag inside the
        # signature loses its opening "<" to Graph-side QP corruption and
        # leaks as literal text once unescaped — cutting the whole block
        # avoids ever parsing that corrupted markup.
        body = {
            "contentType": "html",
            "content": (
                "<div>Thanks, see you then!</div>"
                '<div dir="ltr" class="gmail_signature" data-smartmail="gmail_signature">'
                '<div dir="ltr"><table><tbody><tr><td>'
                '=span style=&quot;margin-right:10px&quot;&gt;Dr Sam Donegan'
                "</td></tr></tbody></table></div></div>"
            ),
        }
        result = _strip_html(body)
        assert "Thanks, see you then!" in result
        assert "Dr Sam Donegan" not in result
        assert "=span style=" not in result

    def test_strips_gmail_signature_block_via_class_marker_alone(self):
        body = {
            "contentType": "html",
            "content": (
                "<div>My reply</div>"
                '<div class="gmail_signature"><div>Real Name<br>Some Company</div></div>'
            ),
        }
        result = _strip_html(body)
        assert "My reply" in result
        assert "Some Company" not in result

    def test_signature_cut_does_not_leave_dangling_tag_fragment(self):
        # real shape (2026-09-17): the signature marker sits mid-attribute
        # inside the enclosing <div ...>, e.g.
        # <div dir="ltr" class="gmail_signature" ...> — cutting at the
        # marker's own position instead of the tag's opening "<" used to
        # leave a dangling '<div dir="ltr"' fragment at the very end of
        # the result, since it has no closing ">" left to be stripped.
        body = {
            "contentType": "html",
            "content": (
                "<div>My reply</div>"
                '<div dir="ltr" class="gmail_signature" data-smartmail="gmail_signature">'
                "Real Name</div>"
            ),
        }
        result = _strip_html(body)
        assert result == "My reply"

    def test_signature_cut_before_quote_when_signature_comes_first(self):
        # real shape: signature block, then the gmail_quote chain further
        # down (a reply that also quotes earlier history) — signature
        # should win since it's the earlier cut point.
        body = {
            "contentType": "html",
            "content": (
                "<div>My reply</div>"
                '<div class="gmail_signature">Real Name</div>'
                '<div class="gmail_quote gmail_quote_container">Old quoted text</div>'
            ),
        }
        result = _strip_html(body)
        assert "My reply" in result
        assert "Real Name" not in result
        assert "Old quoted text" not in result
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

    def test_strips_runs_of_garbled_quoted_printable_bytes(self):
        # Real shape found 2026-09-17 in production mail (a Leukaemia
        # Foundation marketing email's invisible "preview text" padding):
        # raw.body.content itself already contains this exact mix of
        # invisible placeholder characters and undecoded quoted-printable
        # byte escapes *before* our own code ever touches it - Graph
        # handed it to us already mangled. Not recoverable (the original
        # bytes are already gone), so the only safe move is deleting the
        # padding block rather than attempting to decode it. Excerpted
        # directly from the real captured content, not idealised.
        body = {
            "contentType": "html",
            "content": (
                "<div>Because of you, change is happening.</div>"
                "<div>͏ =E2�� �=80�"
                " �=BF =80�</div>"
                "<div>Real readable content follows here.</div>"
            ),
        }
        result = _strip_html(body)
        assert "Because of you, change is happening." in result
        assert "Real readable content follows here." in result
        assert "=E2" not in result
        assert "=80" not in result
        assert "=BF" not in result

    def test_strips_html_escaped_tag_exposed_after_unescaping(self):
        # Real shape found 2026-09-17: a Gmail "<name> reacted via Gmail"
        # auto-notification (an emoji reaction on a Slack/email thread)
        # sends a real tag HTML-escaped in the source — literal
        # "&lt;p&gt;" — which doesn't look like a tag to the first
        # _TAG_RE pass (no literal "<" yet), then becomes a real "<p>"
        # only after html.unescape(), too late for that same pass to
        # catch it. Must not leak into the visible text.
        body = {
            "contentType": "html",
            "content": "<div>\U0001F44D&lt;p&gt; Liu Guilan reacted via Gmail</div>",
        }
        result = _strip_html(body)
        assert "<p>" not in result
        assert "reacted via Gmail" in result

    def test_strips_style_block_content_not_just_tags(self):
        # Real shape found 2026-09-17 (Transport Victoria, a real
        # marketing email) — genuinely clean, uncorrupted markup. The
        # bug: _TAG_RE alone only strips the <style>/</style> tags
        # themselves, leaving the raw CSS rules between them as visible
        # text.
        body = {
            "contentType": "html",
            "content": (
                "<html><head><style>\n<!--\n"
                "#layout > tbody > tr > td\n\t{border:none!important}\n"
                "-->\n</style></head>"
                "<body><div>Tap and go with the flow</div></body></html>"
            ),
        }
        result = _strip_html(body)
        assert "Tap and go with the flow" in result
        assert "border:none" not in result
        assert "tbody" not in result

    def test_strips_script_block_content_not_just_tags(self):
        body = {
            "contentType": "html",
            "content": '<div>Hello</div><script>var x = "should not appear";</script><div>Bye</div>',
        }
        result = _strip_html(body)
        assert "Hello" in result
        assert "Bye" in result
        assert "should not appear" not in result

    def test_isolated_equals_sign_survives(self):
        # A single, isolated "=XX"-shaped sequence is common and
        # legitimate (e.g. a query-string parameter visible as link text,
        # or plain prose that happens to contain one) - only a RUN of
        # several separated purely by whitespace is garbage. This must
        # not be touched.
        body = {
            "contentType": "html",
            "content": "<div>See token=ab for details, and also other=cd.</div>",
        }
        result = _strip_html(body)
        assert "token=ab" in result
        assert "other=cd" in result


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

    def test_captures_cc_recipients(self):
        raw = dict(
            self._BASE_RAW,
            ccRecipients=[
                {"emailAddress": {"address": "CC1@Example.com", "name": "Cc One"}},
                {"emailAddress": {"address": "cc2@example.com", "name": None}},
            ],
        )
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.cc_handles == ["cc1@example.com", "cc2@example.com"]  # lowercased
        assert env.cc_display_names == ["Cc One", None]

    def test_no_cc_recipients_when_absent(self):
        env = _to_envelope(self._BASE_RAW, self_handles={"me@example.com"})
        assert env is not None
        assert env.cc_handles == []
        assert env.cc_display_names == []

    def test_is_automated_true_for_other_classification(self):
        raw = dict(self._BASE_RAW, inferenceClassification="other")
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_false_for_focused_classification(self):
        env = _to_envelope(self._BASE_RAW, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is False

    def test_is_automated_true_for_list_unsubscribe_header(self):
        raw = dict(
            self._BASE_RAW,
            internetMessageHeaders=[{"name": "List-Unsubscribe", "value": "<mailto:x@y.com>"}],
        )
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_true_for_lowercase_list_unsubscribe_header_name(self):
        raw = dict(
            self._BASE_RAW,
            internetMessageHeaders=[{"name": "list-unsubscribe", "value": "<mailto:x@y.com>"}],
        )
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_true_for_noreply_local_part(self):
        raw = dict(self._BASE_RAW, **{"from": {"emailAddress": {"address": "noreply@example.com", "name": "Example"}}})
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_true_for_notifications_local_part(self):
        raw = dict(self._BASE_RAW, **{"from": {"emailAddress": {"address": "notifications@github.com", "name": "GitHub"}}})
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_true_for_known_automated_domain(self):
        raw = dict(self._BASE_RAW, **{"from": {"emailAddress": {"address": "updates@sendgrid.net", "name": "SendGrid"}}})
        env = _to_envelope(raw, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is True

    def test_is_automated_false_for_ordinary_sender(self):
        env = _to_envelope(self._BASE_RAW, self_handles={"me@example.com"})
        assert env is not None
        assert env.is_automated is False


class TestIsAutomated:
    """Direct tests for the standalone is_automated(raw, from_handle)
    function — pulled out of _to_envelope so a backfill can recompute it
    against already-stored raw payloads (see scripts/backfill_is_automated.py)
    without re-deriving from_handle or duplicating the OR expression."""

    def test_true_when_raw_and_from_handle_come_from_a_stored_message(self):
        raw = {
            "inferenceClassification": "focused",
            "internetMessageHeaders": [{"name": "List-Unsubscribe", "value": "<mailto:x@y.com>"}],
        }
        assert is_automated(raw, "someone@example.com") is True

    def test_false_when_nothing_matches(self):
        raw = {"inferenceClassification": "focused", "internetMessageHeaders": []}
        assert is_automated(raw, "eric.tham@example.com") is False

    def test_true_from_from_handle_pattern_alone(self):
        raw = {"inferenceClassification": "focused", "internetMessageHeaders": []}
        assert is_automated(raw, "noreply@example.com") is True
