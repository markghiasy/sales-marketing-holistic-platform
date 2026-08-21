"""Export path (build plan §14, checkpoint after Block A: "Export produces a
complete, re-importable dump.") Thin wrapper over pg_dump/pg_restore rather
than a bespoke format — the store is plain Postgres, no reason to reinvent
this.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime


def export(out_dir: str = "exports") -> str:
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(out_dir, f"comms-store-{stamp}.dump")

    subprocess.run(
        ["pg_dump", "--format=custom", f"--file={out_path}", os.environ["DATABASE_URL"]],
        check=True,
    )
    print(f"exported to {out_path}")  # noqa: T201
    print(f"restore with: pg_restore --clean --if-exists -d <target-db-url> {out_path}")  # noqa: T201
    return out_path


if __name__ == "__main__":
    export(*sys.argv[1:2])
