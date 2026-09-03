"""Rule 5 of §8's identity-resolution ladder: LinkedIn name + organisation
correlation. Never automatic, always queued for human review — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md.
Phase 1: plain string similarity. Phase 2 (not built yet) scores this
with model assistance instead, still always queued.
"""

from __future__ import annotations

from .safety import has_existing_candidate

_NAME_MATCH_SCORE = 0.5
_NO_COMPANY_SCORE = 0.3


def _normalise_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def rule_linkedin_correlation(cur) -> int:
    cur.execute("select id, first_name, last_name, company from linkedin_connection")
    connections = cur.fetchall()
    cur.execute(
        "select id, display_name from identity where channel in ('outlook', 'whatsapp') and display_name is not null"
    )
    other_identities = cur.fetchall()

    count = 0
    for connection_id, first_name, last_name, company in connections:
        if not first_name or not last_name:
            continue
        full_name = _normalise_name(f"{first_name} {last_name}")

        for other_id, other_display_name in other_identities:
            if _normalise_name(other_display_name) != full_name:
                continue

            cur.execute(
                """
                insert into identity (channel, handle, display_name) values ('linkedin', %s, %s)
                on conflict (channel, handle) do update
                    set display_name = excluded.display_name
                    where identity.display_name is null and excluded.display_name is not null
                """,
                (connection_id, f"{first_name} {last_name}".strip()),
            )
            cur.execute("select id from identity where channel = 'linkedin' and handle = %s", (connection_id,))
            linkedin_identity_id = str(cur.fetchone()[0])
            other_identity_id = str(other_id)

            if has_existing_candidate(cur, linkedin_identity_id, other_identity_id):
                continue

            score = _NAME_MATCH_SCORE if company else _NO_COMPANY_SCORE
            reason = (
                f"LinkedIn '{first_name} {last_name}'"
                + (f" @ {company}" if company else "")
                + f" vs '{other_display_name}' — exact normalised name match"
            )
            cur.execute(
                """
                insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason)
                values (%s, %s, %s, 'linkedin_name_company', 'pending', %s)
                """,
                (linkedin_identity_id, other_identity_id, score, reason),
            )
            count += 1
    return count
