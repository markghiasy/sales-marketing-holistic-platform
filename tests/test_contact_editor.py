from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg

from adapters.contact_editor import (
    add_contact_handle,
    get_contact_info,
    link_contact,
    search_identities,
    update_contact_name,
)
from adapters.inbox_query import hide_contact, list_conversations


def _make_identity(cur, channel: str, handle: str, display_name: str | None = None, is_self: bool = False) -> str:
    cur.execute(
        "insert into identity (channel, handle, display_name, is_self) values (%s, %s, %s, %s) returning id",
        (channel, handle, display_name, is_self),
    )
    return str(cur.fetchone()[0])


def _make_thread(cur, channel: str, last_read_at=None) -> str:
    external_id = f"thread-{uuid.uuid4().hex}"
    cur.execute(
        "insert into thread (channel, external_id, last_read_at) values (%s, %s, %s) returning id",
        (channel, external_id, last_read_at),
    )
    return str(cur.fetchone()[0])


def _make_message(cur, thread_id, channel, direction, from_identity_id, participant_ids, sent_at, body_text="hi") -> str:
    external_id = f"msg-{uuid.uuid4().hex}"
    cur.execute(
        """
        insert into message (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, raw)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (thread_id, channel, external_id, direction, sent_at, from_identity_id, body_text, psycopg.types.json.Json({})),
    )
    message_id = str(cur.fetchone()[0])
    for identity_id in participant_ids:
        role = "from" if identity_id == from_identity_id else "to"
        cur.execute(
            "insert into message_participant (message_id, identity_id, role) values (%s, %s, %s)",
            (message_id, identity_id, role),
        )
    return message_id


class TestGetContactInfo:
    def test_returns_name_and_single_handle(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"c-{uuid.uuid4().hex[:8]}@example.com", display_name="Priya Shah")

        info = get_contact_info(cur, contact_id)

        assert info is not None
        assert info.name == "Priya Shah"
        assert len(info.handles) == 1
        assert info.handles[0].channel == "outlook"

    def test_returns_every_handle_for_a_merged_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Priya Shah') returning id")
        person_id = cur.fetchone()[0]
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("outlook", f"priya-{uuid.uuid4().hex[:8]}@example.com", "Priya Shah", person_id),
        )
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net", "Priya Shah", person_id),
        )

        info = get_contact_info(cur, str(person_id))

        assert info is not None
        assert len(info.handles) == 2
        assert {h.channel for h in info.handles} == {"outlook", "whatsapp"}

    def test_returns_none_for_unknown_person_key(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        assert get_contact_info(cur, str(uuid.uuid4())) is None


class TestSearchIdentities:
    def test_finds_matching_handle_substring(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        unique = uuid.uuid4().hex[:8]
        target_id = _make_identity(cur, "outlook", f"zzsearch{unique}@example.com", display_name="Search Target")
        exclude_id = _make_identity(cur, "outlook", f"exclude-{uuid.uuid4().hex[:8]}@example.com", display_name="Excluded")

        results = search_identities(cur, f"zzsearch{unique}", exclude_person_key=exclude_id)

        assert any(r.identity_id == target_id for r in results)

    def test_excludes_identities_already_under_the_given_contact_key(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        unique = uuid.uuid4().hex[:8]
        contact_id = _make_identity(cur, "outlook", f"zzown{unique}@example.com", display_name="Self Match")

        results = search_identities(cur, f"zzown{unique}", exclude_person_key=contact_id)

        assert all(r.identity_id != contact_id for r in results)

    def test_excludes_self_identities(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        unique = uuid.uuid4().hex[:8]
        _make_identity(cur, "outlook", f"zzself{unique}@example.com", display_name="Me", is_self=True)
        exclude_id = _make_identity(cur, "outlook", f"exclude2-{uuid.uuid4().hex[:8]}@example.com")

        results = search_identities(cur, f"zzself{unique}", exclude_person_key=exclude_id)

        assert results == []

    def test_returns_empty_list_for_blank_query(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        exclude_id = _make_identity(cur, "outlook", f"exclude3-{uuid.uuid4().hex[:8]}@example.com")
        assert search_identities(cur, "   ", exclude_person_key=exclude_id) == []


class TestUpdateContactName:
    def test_updates_name_for_every_identity_under_the_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        cur.execute("insert into person (primary_name) values ('Old Name') returning id")
        person_id = cur.fetchone()[0]
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", "Old Name", person_id),
        )
        cur.execute(
            "insert into identity (channel, handle, display_name, person_id) values (%s, %s, %s, %s) returning id",
            ("whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net", "Old Name", person_id),
        )

        update_contact_name(cur, str(person_id), "New Name")

        cur.execute("select distinct display_name from identity where person_id = %s", (person_id,))
        assert [r[0] for r in cur.fetchall()] == ["New Name"]


class TestLinkContact:
    def test_links_an_unresolved_identity_into_the_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Jordan Lee")
        other_id = _make_identity(cur, "whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net")

        link_contact(cur, contact_id, other_id)

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert len(info.handles) == 2
        cur.execute("select person_id from identity where id = %s", (other_id,))
        assert cur.fetchone()[0] is not None

    def test_raises_for_unknown_person_key(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        other_id = _make_identity(cur, "outlook", f"b-{uuid.uuid4().hex[:8]}@example.com")
        try:
            link_contact(cur, str(uuid.uuid4()), other_id)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_update_name_still_works_after_link_with_the_original_stale_person_key(
        self, db_conn: psycopg.Connection
    ):
        # Regression for finding #2: a bare (unresolved) identity's own id
        # is what the frontend opened the contact panel with (person_key).
        # apply_merge() can assign that cluster a brand-new person.id when
        # linking in a second identity, so the identity's own id no longer
        # equals coalesce(person_id, id) afterward. update_contact_name
        # must still resolve the ORIGINAL, now-stale person_key correctly.
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Jordan Lee")
        other_id = _make_identity(cur, "whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net")

        link_contact(cur, contact_id, other_id)

        # contact_id (the original bare identity's own id) is now stale —
        # use it directly, exactly as a frontend still holding the old
        # personKey would.
        update_contact_name(cur, contact_id, "Jordan Renamed")

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert info.name == "Jordan Renamed"

    def test_hidden_contact_stays_hidden_under_the_new_key_after_a_link(self, db_conn: psycopg.Connection):
        # Regression for finding #10: hiding a contact writes a
        # contact_hidden row keyed on its pre-merge contact_key. Linking
        # another identity in can move the cluster to a brand-new
        # person_id (see apply_merge), which must not orphan the hide.
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex[:8]}@example.com", is_self=True)
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Hidden Person")
        other_id = _make_identity(cur, "whatsapp", f"{uuid.uuid4().int % 10**10}@s.whatsapp.net")
        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)

        hide_contact(cur, contact_id)
        new_key = link_contact(cur, contact_id, other_id)

        rows = list_conversations(cur, show_hidden=True)
        assert any(r.person_key == new_key for r in rows)

    def test_linking_two_already_hidden_resolved_contacts_does_not_collide(
        self, db_conn: psycopg.Connection
    ):
        # Regression for the re-review's Important finding on #10: when
        # BOTH identities are already resolved (each has its own person_id)
        # and BOTH are hidden, apply_merge's union branch reuses one side's
        # existing person_id as new_contact_key -- which already owns its
        # own contact_hidden row (contact_key is a primary key), so a plain
        # UPDATE would raise a unique-violation. The fix must survive this
        # without erroring, leaving exactly one hide row under the surviving key.
        cur = db_conn.cursor()
        self_id = _make_identity(cur, "outlook", f"me-{uuid.uuid4().hex[:8]}@example.com", is_self=True)

        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Contact A")
        cur.execute("insert into person (primary_name) values ('Contact A') returning id")
        person_a = cur.fetchone()[0]
        cur.execute("update identity set person_id = %s where id = %s", (person_a, contact_id))

        other_id = _make_identity(cur, "outlook", f"b-{uuid.uuid4().hex[:8]}@example.com", display_name="Contact B")
        cur.execute("insert into person (primary_name) values ('Contact B') returning id")
        person_b = cur.fetchone()[0]
        cur.execute("update identity set person_id = %s where id = %s", (person_b, other_id))

        now = datetime.now(UTC)
        thread_id = _make_thread(cur, "outlook", last_read_at=now)
        _make_message(cur, thread_id, "outlook", "inbound", contact_id, [contact_id, self_id], now)
        _make_message(cur, thread_id, "outlook", "inbound", other_id, [other_id, self_id], now)

        hide_contact(cur, str(person_a))
        hide_contact(cur, str(person_b))

        new_key = link_contact(cur, str(person_a), other_id)  # must not raise

        cur.execute("select count(*) from contact_hidden where contact_key = %s", (new_key,))
        assert cur.fetchone()[0] == 1
        cur.execute("select count(*) from contact_hidden")
        assert cur.fetchone()[0] == 1  # the losing key's row is gone, not just uncounted


class TestAddContactHandle:
    def test_adds_a_new_bare_identity_under_the_contact(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        new_email = f"personal-{uuid.uuid4().hex[:8]}@gmail.com"

        add_contact_handle(cur, contact_id, new_email)

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert any(h.handle == new_email.lower() and h.channel == "outlook" for h in info.handles)

    def test_guesses_whatsapp_channel_for_a_bare_phone_number(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        phone = str(61400000000 + (uuid.uuid4().int % 900000))

        add_contact_handle(cur, contact_id, phone)

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert any(h.channel == "whatsapp" and h.handle == f"{phone}@s.whatsapp.net" for h in info.handles)

    def test_raises_when_handle_already_exists(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        existing_email = f"taken-{uuid.uuid4().hex[:8]}@example.com"
        _make_identity(cur, "outlook", existing_email)

        try:
            add_contact_handle(cur, contact_id, existing_email)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_guesses_whatsapp_channel_for_a_formatted_phone_number(self, db_conn: psycopg.Connection):
        # Regression for finding #11: a human-formatted number like
        # "+61 400 000 000" has spaces the old digits_only == text.lstrip("+")
        # check didn't tolerate, so it fell through to the outlook (email)
        # branch and got stored lowercased as a bogus email-channel handle.
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        digits = str(61400000000 + (uuid.uuid4().int % 900000))
        formatted = f"+{digits[:2]} {digits[2:5]} {digits[5:8]} {digits[8:]}"

        add_contact_handle(cur, contact_id, formatted)

        info = get_contact_info(cur, contact_id)
        assert info is not None
        assert any(h.channel == "whatsapp" and h.handle == f"{digits}@s.whatsapp.net" for h in info.handles)

    def test_creates_a_person_row_when_contact_has_none_yet(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        contact_id = _make_identity(cur, "outlook", f"a-{uuid.uuid4().hex[:8]}@example.com", display_name="Sam Kim")
        cur.execute("select person_id from identity where id = %s", (contact_id,))
        assert cur.fetchone()[0] is None  # not yet resolved, confirms this test's premise

        add_contact_handle(cur, contact_id, f"new-{uuid.uuid4().hex[:8]}@example.com")

        cur.execute("select person_id from identity where id = %s", (contact_id,))
        assert cur.fetchone()[0] is not None
