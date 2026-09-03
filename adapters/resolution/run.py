"""Entrypoint for identity resolution + Phase 1 structured knowledge-graph
facts. Run: python -m adapters.resolution.run

Deliberately manual, not scheduled — see
docs/superpowers/specs/2026-09-03-identity-resolution-design.md,
"Architecture".
"""

from __future__ import annotations

import os
import sys

import psycopg
from dotenv import load_dotenv

from .linkedin_correlation import rule_linkedin_correlation
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


if __name__ == "__main__":
    run()
