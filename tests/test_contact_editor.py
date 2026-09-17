from __future__ import annotations

import uuid

import psycopg

from adapters.contact_editor import get_contact_info, search_identities, update_contact_name


def _make_identity(cur, channel: str, handle: str, display_name: str | None = None, is_self: bool = False) -> str:
    cur.execute(
        "insert into identity (channel, handle, display_name, is_self) values (%s, %s, %s, %s) returning id",
        (channel, handle, display_name, is_self),
    )
    return str(cur.fetchone()[0])


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
