"""Entrypoint for identity resolution + Phase 1 structured knowledge-graph
facts. Run: python -m adapters.resolution.run

Called automatically after every channel sync (see run_best_effort() below
and each adapter's own sync.py) — no longer purely manual as
docs/superpowers/specs/2026-09-03-identity-resolution-design.md originally
described; that design predates real usage. Safe to call this often since
every Phase 1 rule is free (no model call).
"""

from __future__ import annotations

import os
import sys
import traceback

import psycopg
from dotenv import load_dotenv

from .linkedin_correlation import rule_linkedin_correlation, rule_linkedin_dedupe
from .rules import rule_contact_bridge, rule_exact_email_match, rule_signature_phone
from .structured_facts import extract_structured_facts


def run() -> None:
    # built inside the function, not at module scope — a module-level
    # list would capture these function objects once at import time,
    # and a test patching e.g. "adapters.resolution.run.rule_exact_email_match"
    # afterward would never reach it (the patch replaces the module
    # attribute, not the reference already stored in the list), so the
    # rule functions must be looked up fresh on every call
    rules = [
        ("exact email match", rule_exact_email_match),
        ("contact bridge", rule_contact_bridge),
        ("signature phone", rule_signature_phone),
        ("LinkedIn name+company correlation", rule_linkedin_correlation),
        ("LinkedIn same-channel dedupe", rule_linkedin_dedupe),
        ("structured facts", extract_structured_facts),
    ]

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:  # noqa: SIM117
        with conn.cursor() as cur:
            for label, rule_fn in rules:
                try:
                    count = rule_fn(cur)
                    conn.commit()
                    print(f"{label}: {count}")
                except Exception as e:  # noqa: BLE001 — one rule's bug must not block the rest
                    conn.rollback()
                    print(f"{label}: FAILED — {e}", file=sys.stderr)


def run_best_effort() -> None:
    """Same as run(), except a total failure here (e.g. the database is
    unreachable) is caught and logged rather than raised — called from
    each channel's own sync.py after a successful sync, where a
    resolution problem must never make the calling sync job look like it
    failed. run() already isolates each rule's own failure internally;
    this is the second, outer layer of isolation for the call itself."""
    try:
        run()
    except Exception as e:  # noqa: BLE001 — resolution failing must never fail the caller's sync
        print(f"identity resolution run failed (the sync itself still succeeded): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    run()
