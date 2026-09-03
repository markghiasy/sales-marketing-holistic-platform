"""Chooses person.primary_name / preferred_name from the display names of
every identity being merged into one person — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
"Naming a merged person". Best-effort, not a guarantee.
"""

from __future__ import annotations

import re

_NAME_LIKE_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]*(\s+[A-Za-z][A-Za-z'\-]*)*$")


def _looks_name_like(candidate: str) -> bool:
    """One or more alphabetic tokens separated by spaces (allowing
    apostrophes/hyphens within a token, e.g. "O'Brien") — a single word
    like "Eric" passes (it's a plausible short/preferred name), but
    anything with digits or underscores, like a username, doesn't."""
    return bool(_NAME_LIKE_RE.match(candidate.strip()))


def select_names(display_names: list[str | None]) -> tuple[str, str | None]:
    """Returns (primary_name, preferred_name). display_names is every
    identity's display_name in the resulting merged cluster, in no
    particular order. Raises ValueError if given no candidates at all
    (a merge always involves at least one real identity)."""
    candidates = [d.strip() for d in display_names if d and d.strip()]
    if not candidates:
        raise ValueError("select_names requires at least one non-empty candidate")

    name_like = [c for c in candidates if _looks_name_like(c)]

    if not name_like:
        return candidates[0], None

    name_like_sorted = sorted(set(name_like), key=len, reverse=True)
    primary = name_like_sorted[0]
    shorter_distinct = [c for c in name_like_sorted[1:] if c != primary]
    preferred = shorter_distinct[0] if shorter_distinct else None
    return primary, preferred
