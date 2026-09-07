"""Knowledge-graph facts from structured sources that are already fully
ingested and need no model call — Phase 1 of the §10 knowledge-graph
upgrade. See
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
Scope item 7.
"""

from __future__ import annotations

from .organizations import get_or_create_organization, normalise_org_name


def _get_or_create_linkedin_identity(cur, connection_id: str, display_name: str | None) -> str:
    cur.execute(
        """
        insert into identity (channel, handle, display_name) values ('linkedin', %s, %s)
        on conflict (channel, handle) do update
            set display_name = coalesce(identity.display_name, excluded.display_name)
        returning id
        """,
        (connection_id, display_name),
    )
    # the on conflict clause has no WHERE, so it always fires and
    # RETURNING always yields a row — no separate SELECT needed, even
    # when the update is a same-value no-op
    return str(cur.fetchone()[0])


def extract_structured_facts(cur) -> int:
    cur.execute("select id, first_name, last_name, company, position from linkedin_connection")
    connections = cur.fetchall()

    # loaded once instead of re-derived per connection: with thousands of
    # real connections, a select-then-maybe-insert per fact and a fresh
    # organization lookup per company were the dominant cost of a real run
    # against the hosted database — one to several network round trips per
    # connection, most of them re-confirming facts already extracted on a
    # prior run.
    cur.execute("select handle, id, display_name from identity where channel = 'linkedin'")
    identity_by_handle = {
        handle: (str(identity_id), display_name) for handle, identity_id, display_name in cur.fetchall()
    }

    cur.execute(
        "select subject_identity_id, fact_type, object_org_id, object_text from fact "
        "where fact_type in ('works_at', 'has_title')"
    )
    existing_facts = {
        (str(subject_id), fact_type, str(org_id) if org_id else None, object_text)
        for subject_id, fact_type, org_id, object_text in cur.fetchall()
    }

    org_cache: dict[str, str] = {}

    def cached_org_id(raw_name: str) -> str:
        canonical = normalise_org_name(raw_name)
        if canonical not in org_cache:
            org_cache[canonical] = get_or_create_organization(cur, raw_name)
        return org_cache[canonical]

    count = 0
    for connection_id, first_name, last_name, company, position in connections:
        display_name = f"{first_name or ''} {last_name or ''}".strip() or None
        cached = identity_by_handle.get(connection_id)
        # skip the upsert round trip only when it's provably a no-op: the
        # identity already exists AND already has a display_name (so there's
        # nothing left for the backfill to do). Otherwise fall through to
        # the real upsert, same as an uncached connection.
        if cached is not None and cached[1] is not None:
            identity_id = cached[0]
        else:
            identity_id = _get_or_create_linkedin_identity(cur, connection_id, display_name)
            identity_by_handle[connection_id] = (identity_id, display_name or (cached[1] if cached else None))

        if company:
            org_id = cached_org_id(company)
            key = (identity_id, "works_at", org_id, None)
            if key not in existing_facts:
                cur.execute(
                    """
                    insert into fact
                        (subject_identity_id, fact_type, object_org_id, confidence, source, status)
                    values (%s, 'works_at', %s, 1.0, 'linkedin_connection', 'confirmed')
                    """,
                    (identity_id, org_id),
                )
                existing_facts.add(key)
                count += 1

        if position:
            key = (identity_id, "has_title", None, position)
            if key not in existing_facts:
                cur.execute(
                    """
                    insert into fact
                        (subject_identity_id, fact_type, object_text, confidence, source, status)
                    values (%s, 'has_title', %s, 1.0, 'linkedin_connection', 'confirmed')
                    """,
                    (identity_id, position),
                )
                existing_facts.add(key)
                count += 1
    return count
