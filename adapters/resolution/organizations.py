"""Canonical organisation dedup for knowledge-graph facts — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
"Canonical organisations, not free text". Exact-normalised-name dedup
only; deliberately no fuzzy variant matching (that's the kind of guess
that creates false merges, just for companies instead of people).
"""

from __future__ import annotations

import re

_SUFFIX_RE = re.compile(
    r"\s+(inc|inc\.|ltd|ltd\.|llc|co|co\.|corp|corp\.)$", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"\s+")


def normalise_org_name(raw_name: str) -> str:
    name = raw_name.strip()
    name = _SUFFIX_RE.sub("", name)
    name = _WHITESPACE_RE.sub(" ", name).strip()
    return name.lower()


def get_or_create_organization(cur, raw_name: str) -> str:
    canonical = normalise_org_name(raw_name)
    cur.execute(
        """
        insert into organization (canonical_name)
        values (%s)
        on conflict (canonical_name) do update set canonical_name = excluded.canonical_name
        returning id
        """,
        (canonical,),
    )
    return str(cur.fetchone()[0])
