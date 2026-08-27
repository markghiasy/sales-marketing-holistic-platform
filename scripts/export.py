"""Export path (build plan §14, checkpoint after Block A: "Export produces a
complete, re-importable dump.") Thin wrapper over pg_dump/pg_restore rather
than a bespoke format — the store is plain Postgres, no reason to reinvent
this.

Runs pg_dump inside a throwaway `postgres:16` container instead of
shelling out to a host-installed client — found via the fresh-deploy
checkpoint (§2/§14) that a clean machine has no pg_dump on PATH at all,
so the old direct-subprocess version failed outright on a real clean
checkout, not just untested as the runbook previously noted. Connecting
out over the network like this also means it works the same way whether
DATABASE_URL points at the local docker-compose Postgres or a remote
host (e.g. the hosted Supabase instance) — nothing here assumes the
target is a sibling container.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv


def _db_url_for_container(url: str) -> str:
    # "localhost" inside the throwaway pg_dump container refers to that
    # container itself, not the host running docker-compose's Postgres —
    # host.docker.internal is Docker Desktop's (Windows/Mac) resolvable
    # name for the host machine. Only the local-dev case needs this;
    # a remote host (e.g. Supabase) is unaffected either way.
    return url.replace("@localhost:", "@host.docker.internal:").replace(
        "@127.0.0.1:", "@host.docker.internal:"
    )


def export(out_dir: str = "exports") -> str:
    load_dotenv()
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"comms-store-{stamp}.dump"
    out_path = os.path.join(out_dir, filename)

    subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{out_dir_abs}:/out",
            "postgres:16",
            "pg_dump", "--format=custom", f"--file=/out/{filename}",
            _db_url_for_container(os.environ["DATABASE_URL"]),
        ],
        check=True,
    )
    print(f"exported to {out_path}")
    # --no-owner: the exporting and restoring roles are almost never the
    # same (e.g. exporting from Supabase's `postgres` role, restoring
    # into a fresh local `comms` role) — without it, every OWNER TO
    # statement in the dump errors out on a role that doesn't exist on
    # the target. Harmless to the actual data, but noisy; verified by
    # restoring a real export into a differently-named role and getting
    # 14 of these before adding the flag.
    print(f"restore with: pg_restore --clean --if-exists --no-owner -d <target-db-url> {out_path}")
    return out_path


if __name__ == "__main__":
    export(*sys.argv[1:2])
