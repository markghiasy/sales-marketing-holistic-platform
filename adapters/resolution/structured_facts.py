"""Knowledge-graph facts from structured sources that are already fully
ingested and need no model call — Phase 1 of the §10 knowledge-graph
upgrade. See
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
Scope item 7.
"""

from __future__ import annotations

from .organizations import get_or_create_organization


def _get_or_create_linkedin_identity(cur, connection_id: str) -> str:
    cur.execute(
        "insert into identity (channel, handle) values ('linkedin', %s) on conflict (channel, handle) do nothing",
        (connection_id,),
    )
    cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (connection_id,))
    return str(cur.fetchone()[0])


def extract_structured_facts(cur) -> int:
    cur.execute("select id, company, position from linkedin_connection")
    connections = cur.fetchall()
    count = 0
    for connection_id, company, position in connections:
        identity_id = _get_or_create_linkedin_identity(cur, connection_id)

        if company:
            org_id = get_or_create_organization(cur, company)
            cur.execute(
                "select 1 from fact where subject_identity_id = %s and fact_type = 'works_at' and object_org_id = %s",
                (identity_id, org_id),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    insert into fact
                        (subject_identity_id, fact_type, object_org_id, confidence, source, status)
                    values (%s, 'works_at', %s, 1.0, 'linkedin_connection', 'confirmed')
                    """,
                    (identity_id, org_id),
                )
                count += 1

        if position:
            cur.execute(
                "select 1 from fact where subject_identity_id = %s and fact_type = 'has_title' and object_text = %s",
                (identity_id, position),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    insert into fact
                        (subject_identity_id, fact_type, object_text, confidence, source, status)
                    values (%s, 'has_title', %s, 1.0, 'linkedin_connection', 'confirmed')
                    """,
                    (identity_id, position),
                )
                count += 1
    return count
