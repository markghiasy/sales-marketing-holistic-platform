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
import subprocess
import sys
import traceback
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from .linkedin_correlation import rule_linkedin_correlation
from .rules import (
    rule_contact_bridge,
    rule_exact_email_match,
    rule_outlook_dedupe,
    rule_signature_phone,
)
from .structured_facts import extract_structured_facts

RULE_VERSION = "2026-09-30-suggestions-v1"


def code_revision() -> str:
    """Local metadata only; unknown for an archive without release metadata."""
    if os.environ.get("IRONMAN_RELEASE"):
        return os.environ["IRONMAN_RELEASE"][:128]
    root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=3, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


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
        ("Outlook same-channel dedupe", rule_outlook_dedupe),
        ("LinkedIn name+company correlation", rule_linkedin_correlation),
        ("structured facts", extract_structured_facts),
    ]

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:  # noqa: SIM117
        with conn.cursor() as cur:
            cur.execute("insert into resolution_run(code_revision) values (%s) returning id",
                        (code_revision(),))
            run_id = str(cur.fetchone()[0])
            conn.commit()
            results = []
            for label, rule_fn in rules:
                try:
                    cur.execute("select set_config('ironman.resolution_run',%s,true), "
                                "set_config('ironman.rule_version',%s,true)", (run_id, RULE_VERSION))
                    cur.execute("select count(*) from link_candidate where run_id=%s", (run_id,))
                    before = cur.fetchone()[0]
                    count = rule_fn(cur)
                    cur.execute("select count(*) from link_candidate where run_id=%s", (run_id,))
                    written = cur.fetchone()[0] - before
                    conn.commit()
                    kind = "detections_only" if label == "signature phone" else "rule_results"
                    results.append({"rule": label, "status": "success", "reported_count": count,
                                        "candidates_written": written, "count_kind": kind})
                    print(f"{label}: {count} {kind}; {written} candidates written; run {run_id}")
                except Exception as e:  # noqa: BLE001 — one rule's bug must not block the rest
                    conn.rollback()
                    results.append({"rule": label, "status": "failed", "error_type": type(e).__name__})
                    print(f"{label}: FAILED — {e}", file=sys.stderr)
            status = "partial_failure" if any(r["status"] == "failed" for r in results) else "success"
            cur.execute("update resolution_run set finished_at=now(),status=%s,results=%s where id=%s",
                        (status, psycopg.types.json.Json(results), run_id))
            conn.commit()


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
