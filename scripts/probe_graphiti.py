"""Report prerequisites honestly; never interpret missing setup as a benchmark."""

import importlib.util
import json
import os
from pathlib import Path


def preflight(*, package_available=None, store_configured=None):
    if package_available is None:
        package_available = importlib.util.find_spec("graphiti_core") is not None
    if store_configured is None:
        store_configured = bool(os.environ.get("GRAPHITI_PROBE_URI"))
    missing = []
    if not package_available:
        missing.append("graphiti_core")
    if not store_configured:
        missing.append("isolated graph store")
    return {
        "status": "unexecuted",
        "stage": "prerequisite check",
        "missing": missing,
        "reason": "Extraction/retrieval trial requires an isolated graph store, pinned SDK and explicitly bounded model-call configuration. This preflight performs no model calls.",
        "next_checks": [
            "Canonical UUID preservation under deduplication",
            "Concurrent roles versus superseded employer",
            "Late evidence and source references",
            "Review-state separation and correction/undo",
        ],
    }


if __name__ == "__main__":
    result = preflight()
    target = (
        Path(__file__).resolve().parents[1] / "docs/research/network-demo/graphiti-preflight.json"
    )
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
