"""Explicit release check for aggregate-only resolution measurement attestations."""

import argparse
import json
from pathlib import Path

from adapters.resolution.quality import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attestation", type=Path)
    parser.add_argument("--expected-code-version", required=True)
    parser.add_argument("--expected-ruleset-version", required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.attestation.read_text(encoding="utf-8"))
        result = evaluate(
            report,
            expected_code_version=args.expected_code_version,
            expected_ruleset_version=args.expected_ruleset_version,
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        result = {
            "status": "invalid",
            "promotable": False,
            "issues": ["Cannot read an aggregate JSON attestation."],
        }
    print(json.dumps(result, indent=2))
    return {"pass": 0, "fail": 1, "measurement_pending": 2, "invalid": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
