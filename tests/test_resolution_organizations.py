# tests/test_resolution_organizations.py
from __future__ import annotations

import psycopg

from adapters.resolution.organizations import get_or_create_organization, normalise_org_name


class TestNormaliseOrgName:
    def test_lowercases_and_trims(self):
        assert normalise_org_name("  Acme  ") == "acme"

    def test_strips_common_suffixes(self):
        assert normalise_org_name("Acme Inc") == "acme"
        assert normalise_org_name("Acme Inc.") == "acme"
        assert normalise_org_name("Acme Ltd") == "acme"
        assert normalise_org_name("Acme Corp") == "acme"

    def test_does_not_merge_genuine_variants(self):
        # this is the point of NOT doing fuzzy matching — these stay
        # different normalised strings on purpose
        assert normalise_org_name("Commonwealth Bank") != normalise_org_name("CBA")


class TestGetOrCreateOrganization:
    def test_creates_a_new_organization(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        org_id = get_or_create_organization(cur, "Acme Inc")

        cur.execute("select canonical_name from organization where id = %s", (org_id,))
        assert cur.fetchone()[0] == "acme"

    def test_reuses_existing_organization_for_a_suffix_variant(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        id1 = get_or_create_organization(cur, "Acme Inc")
        id2 = get_or_create_organization(cur, "Acme")

        assert id1 == id2

    def test_keeps_genuine_variants_as_separate_rows(self, db_conn: psycopg.Connection):
        cur = db_conn.cursor()
        id1 = get_or_create_organization(cur, "Commonwealth Bank")
        id2 = get_or_create_organization(cur, "CBA")

        assert id1 != id2
