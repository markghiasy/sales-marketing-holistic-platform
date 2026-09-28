"""Aggregate-only quality gates; all fixtures are invented, never private pairs."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from adapters.resolution.quality import evaluate, wilson_lower


def report(arm="review_queue", same=90, different=10, unknown=20):
    return {
        "schema_version": 1,
        "policy_id": "resolution-quality-2026-09-28",
        "arm": arm,
        "code_version": "a" * 40,
        "ruleset_version": "synthetic-rules-v1",
        "changed_rules": ["synthetic_rule"],
        "preregistration": {
            "commit": "b" * 40,
            "registered_at": "2026-09-28T01:00:00Z",
            "sampling_plan": "Uniform random sample of this arm's emitted positives.",
            "holdout_id": "synthetic-fresh-holdout",
        },
        "measurement": {
            "sampled_at": "2026-09-29T01:00:00Z",
            "graded_at": "2026-09-30T01:00:00Z",
            "fresh_holdout": True,
            "blind_to_rule_and_decision": True,
            "own_positives": True,
            "representative_queue_sample": arm == "review_queue",
            "same": same,
            "different": different,
            "unknown": unknown,
            "by_rule": [
                {
                    "rule": "synthetic_rule",
                    "rule_version": "v1",
                    "same": same,
                    "different": different,
                    "unknown": unknown,
                }
            ],
        },
    }


def check(data):
    return evaluate(
        data, expected_code_version="a" * 40, expected_ruleset_version="synthetic-rules-v1"
    )


def test_wilson_uses_two_sided_95_percent_not_point_estimate():
    assert wilson_lower(99, 100) == pytest.approx(0.945513803821)
    assert wilson_lower(400, 400) == pytest.approx(0.990487705666)
    assert wilson_lower(0, 0) is None


def test_unknowns_remain_visible_without_entering_scored_denominator():
    result = check(report())
    assert result["status"] == "pass"
    assert result["metrics"]["scored"] == 100
    assert result["metrics"]["total"] == 120
    assert result["metrics"]["unknown_rate"] == pytest.approx(1 / 6)
    assert result["metrics"]["precision"] == 0.9


def test_review_gate_is_queue_level_not_per_rule():
    data = report(same=91, different=9, unknown=0)
    data["measurement"]["by_rule"] = [
        {"rule": "synthetic_rule", "rule_version": "v1", "same": 1, "different": 9, "unknown": 0},
        {"rule": "other_rule", "rule_version": "v3", "same": 90, "different": 0, "unknown": 0},
    ]
    assert check(data)["status"] == "pass"


def test_high_precision_below_minimum_is_pending_not_pass():
    result = check(report(same=60, different=0, unknown=150))
    assert result["status"] == "measurement_pending"


def test_low_queue_precision_fails_even_with_enough_scored_pairs():
    assert check(report(same=70, different=30))["status"] == "fail"


def test_auto_merge_has_separate_stricter_gate():
    assert check(report("auto_merge", 400, 0, 0))["status"] == "pass"
    assert check(report("auto_merge", 399, 1, 0))["status"] == "fail"
    assert check(report("auto_merge", 100, 0, 0))["status"] == "measurement_pending"


def test_auto_rule_cannot_be_hidden_in_pooled_successes():
    data = report("auto_merge", 499, 1, 0)
    data["measurement"]["by_rule"] = [
        {"rule": "synthetic_rule", "rule_version": "v1", "same": 99, "different": 1, "unknown": 0},
        {"rule": "other_rule", "rule_version": "v3", "same": 400, "different": 0, "unknown": 0},
    ]
    assert check(data)["status"] == "measurement_pending"


@pytest.mark.parametrize(
    "field",
    ["fresh_holdout", "blind_to_rule_and_decision", "own_positives", "representative_queue_sample"],
)
def test_invalid_sampling_cannot_pass(field):
    data = report()
    data["measurement"][field] = False
    assert check(data)["status"] == "invalid"


def test_preregistration_after_sampling_cannot_pass():
    data = report()
    data["preregistration"]["registered_at"] = "2026-10-01T00:00:00Z"
    assert check(data)["status"] == "invalid"


@pytest.mark.parametrize("field", ["code_version", "ruleset_version"])
def test_stale_measurement_cannot_release_changed_code(field):
    data = report()
    data[field] = "c" * 40
    assert check(data)["status"] == "invalid"


def test_missing_measurement_or_preregistration_is_pending():
    for key in ("measurement", "preregistration"):
        data = report()
        data[key] = None
        assert check(data)["status"] == "measurement_pending"


def test_unfinished_aggregate_record_is_pending_not_a_pass():
    data = report()
    del data["measurement"]["unknown"]
    assert check(data)["status"] == "measurement_pending"


def test_counts_must_be_nonnegative_integers_and_reconcile():
    for bad in (-1, True, 1.5):
        data = report()
        data["measurement"]["same"] = bad
        assert check(data)["status"] == "invalid"
    data = report()
    data["measurement"]["by_rule"][0]["same"] -= 1
    assert check(data)["status"] == "invalid"


def test_changed_rule_with_no_own_positives_is_pending():
    data = report()
    data["changed_rules"].append("new_rule_without_samples")
    assert check(data)["status"] == "measurement_pending"


def test_report_cannot_override_preregistered_threshold():
    data = report(same=70, different=30)
    data["threshold"] = 0.1
    assert check(data)["status"] == "invalid"


def test_cli_exits_nonzero_for_pending_and_zero_only_for_pass(tmp_path):
    path = tmp_path / "aggregate.json"
    data = report()
    command = [
        sys.executable,
        "-m",
        "scripts.check_resolution_quality",
        str(path),
        "--expected-code-version",
        "a" * 40,
        "--expected-ruleset-version",
        "synthetic-rules-v1",
    ]
    for measurement, expected_exit in [(None, 2), (deepcopy(data["measurement"]), 0)]:
        data["measurement"] = measurement
        path.write_text(json.dumps(data), encoding="utf-8")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == expected_exit, result.stderr
        assert json.loads(result.stdout)["status"] in ("measurement_pending", "pass")


def test_published_template_never_claims_a_measured_pass():
    path = Path("docs/quality/resolution-measurement.template.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert check(data)["status"] == "measurement_pending"
