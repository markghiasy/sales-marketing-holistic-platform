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


_SAME_NAME_SCORE = 0.6


def rule_linkedin_dedupe(cur) -> int:
    """LinkedIn contacts can end up as two separate identity rows for the
    same real person: one from the CSV connections export (handle = their
    profile URL), one from the live network scraper (handle = their
    urn:li:fsd_profile:... id) — nothing links the two shapes together.
    Found 2026-09-18 against real data: 18 real LinkedIn contacts (Tom
    Nguyen, Chalara Chiarelli, ...) each showed up as two separate rows in
    the triage inbox as a result. Same "never automatic, always queued"
    policy as rule_linkedin_correlation above — an exact name match alone
    isn't enough confidence to auto-merge (two different real people can
    share a name), so this only ever proposes a link_candidate. Company
    is only ever known for the profile-URL-shaped identity (via
    linkedin_connection) — the urn-shaped one carries none — so it can't
    be cross-checked on both sides; it's included in the reason text as a
    hint for whoever reviews the candidate, not as a match condition.
    """
    cur.execute(
        """
        select id, handle, display_name from identity
        where channel = 'linkedin' and is_self = false
          and display_name is not null and person_id is null
        """
    )
    identities = cur.fetchall()

    by_name: dict[str, list[tuple[str, str, str]]] = {}
    for identity_id, handle, display_name in identities:
        by_name.setdefault(_normalise_name(display_name), []).append(
            (str(identity_id), handle, display_name)
        )

    count = 0
    for group in by_name.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                (id_a, handle_a, name_a), (id_b, handle_b, name_b) = group[i], group[j]
                if has_existing_candidate(cur, id_a, id_b):
                    continue

                cur.execute(
                    "select company from linkedin_connection where id in (lower(%s), lower(%s))",
                    (handle_a, handle_b),
                )
                company_row = cur.fetchone()
                company = company_row[0] if company_row else None

                reason = (
                    f"LinkedIn '{name_a}' ({handle_a}) vs '{name_b}' ({handle_b}) — "
                    "exact normalised name match, same channel, different handle shape "
                    "(CSV export profile URL vs live-scraper urn)"
                    + (f". Known company: {company}" if company else "")
                )
                cur.execute(
                    """
                    insert into link_candidate (identity_a_id, identity_b_id, score, method, status, reason)
                    values (%s, %s, %s, 'linkedin_same_channel_dedupe', 'pending', %s)
                    """,
                    (id_a, id_b, _SAME_NAME_SCORE, reason),
                )
                count += 1
    return count
