"""Aggregate-only release gate. Never loads private pairs, secrets, or a database.

This validates an accountable attestation, not the truth of its declarations.
The private sampling/grading workflow remains with the data owner.
"""

from datetime import datetime
from math import sqrt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

POLICY_ID = "resolution-quality-2026-09-28"
MARKS = {"review_queue": (0.70, 100), "auto_merge": (0.99, 400)}
Z_95 = 1.959963984540054  # Lower endpoint of the TWO-SIDED 95% Wilson interval.


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Counts(Strict):
    same: int = Field(ge=0)
    different: int = Field(ge=0)
    unknown: int = Field(ge=0)


class RuleCounts(Counts):
    rule: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)


class Preregistration(Strict):
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    registered_at: str
    sampling_plan: str = Field(min_length=1)
    holdout_id: str = Field(min_length=1)


class Measurement(Counts):
    sampled_at: str
    graded_at: str
    fresh_holdout: bool
    blind_to_rule_and_decision: bool
    own_positives: bool
    representative_queue_sample: bool
    by_rule: list[RuleCounts] = Field(min_length=1)


class Attestation(Strict):
    schema_version: Literal[1]
    policy_id: Literal["resolution-quality-2026-09-28"]
    arm: Literal["review_queue", "auto_merge"]
    code_version: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    ruleset_version: str | None = Field(default=None, min_length=1)
    changed_rules: list[str] = Field(min_length=1)
    preregistration: Preregistration | None = None
    measurement: Measurement | None = None


def wilson_lower(successes: int, scored: int) -> float | None:
    """Return the 95% Wilson lower endpoint; no scored observations => undefined."""
    if type(successes) is not int or type(scored) is not int:
        raise ValueError("Wilson counts must be integers")
    if scored < 0 or successes < 0 or successes > scored:
        raise ValueError("Invalid Wilson counts")
    if not scored:
        return None
    p = successes / scored
    z2 = Z_95 * Z_95
    return max(
        0.0,
        (p + z2 / (2 * scored) - Z_95 * sqrt(p * (1 - p) / scored + z2 / (4 * scored**2)))
        / (1 + z2 / scored),
    )


def metrics(counts: Counts) -> dict:
    scored = counts.same + counts.different
    total = scored + counts.unknown
    return {
        "same": counts.same,
        "different": counts.different,
        "unknown": counts.unknown,
        "scored": scored,
        "total": total,
        "precision": counts.same / scored if scored else None,
        "unknown_rate": counts.unknown / total if total else None,
        "wilson_95_lower": wilson_lower(counts.same, scored),
    }


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return result


def evaluate(report: dict, *, expected_code_version: str, expected_ruleset_version: str) -> dict:
    """Pass only a complete, matching attestation meeting fixed preregistered marks."""
    result = {
        "policy_id": POLICY_ID,
        "status": "invalid",
        "promotable": False,
        "issues": [],
        "metrics": None,
        "rule_diagnostics": [],
    }

    def finish(status, *issues):
        result.update(status=status, promotable=status == "pass", issues=list(issues))
        return result

    try:
        data = Attestation.model_validate(report)
    except ValidationError as error:
        errors = error.errors()
        return finish(
            "measurement_pending" if all(e["type"] == "missing" for e in errors) else "invalid",
            *[".".join(map(str, e["loc"])) + ": " + e["type"] for e in errors],
        )
    result["arm"] = data.arm
    threshold, minimum = MARKS[data.arm]
    result["mark"] = {
        "wilson_95_lower": threshold,
        "minimum_scored": minimum,
        "scope": "whole_queue" if data.arm == "review_queue" else "each_changed_rule",
    }
    result["interpretation"] = (
        "Precision is conditional on scored pairs. Unknowns are not correct matches; "
        "inspect unknown_rate. Sampling and blinding are declarations, not independently verified."
    )
    if not data.code_version or not data.ruleset_version or not data.preregistration:
        return finish("measurement_pending", "Complete and commit preregistration before sampling.")
    if (
        data.code_version != expected_code_version
        or data.ruleset_version != expected_ruleset_version
    ):
        return finish("invalid", "Attestation does not match the intended code/ruleset version.")
    if len(set(data.changed_rules)) != len(data.changed_rules) or any(
        not rule.strip() for rule in data.changed_rules
    ):
        return finish("invalid", "changed_rules must contain unique, nonempty rule names.")
    if data.measurement is None:
        return finish("measurement_pending", "A fresh private measurement has not been supplied.")
    m, prereg = data.measurement, data.preregistration
    result["metrics"] = metrics(m)
    result["rule_diagnostics"] = [
        {"rule": r.rule, "rule_version": r.rule_version, **metrics(r)} for r in m.by_rule
    ]
    try:
        registered, sampled, graded = map(_time, (prereg.registered_at, m.sampled_at, m.graded_at))
        if not registered < sampled <= graded:
            raise ValueError("Preregistration must precede sampling, which must precede grading.")
        policy_date = "2026-09-10" if data.arm == "review_queue" else "2026-09-28"
        if registered.date().isoformat() < policy_date:
            raise ValueError("Registration predates this arm's policy.")
    except (ValueError, TypeError) as error:
        return finish("invalid", str(error))
    if not (m.fresh_holdout and m.blind_to_rule_and_decision and m.own_positives):
        return finish(
            "invalid", "Fresh holdout, blind grading, and own-positive sampling are required."
        )
    if data.arm == "review_queue" and not m.representative_queue_sample:
        return finish("invalid", "Review-queue gate requires a representative whole-queue sample.")
    rules = {r.rule: r for r in m.by_rule}
    if len(rules) != len(m.by_rule):
        return finish("invalid", "Duplicate rule attribution.")
    if any(
        sum(getattr(r, k) for r in m.by_rule) != getattr(m, k)
        for k in ("same", "different", "unknown")
    ):
        return finish(
            "invalid", "Per-rule counts must sum to aggregate same/different/unknown counts."
        )
    if any(rule not in rules or metrics(rules[rule])["total"] == 0 for rule in data.changed_rules):
        return finish("measurement_pending", "Each changed rule needs its own sampled positives.")
    checked = [m] if data.arm == "review_queue" else [rules[name] for name in data.changed_rules]
    if any(metrics(row)["scored"] < minimum for row in checked):
        return finish(
            "measurement_pending", "Insufficient scored pairs for the preregistered gate."
        )
    if any(metrics(row)["wilson_95_lower"] < threshold for row in checked):
        return finish("fail", "Wilson 95% lower bound is below the fixed preregistered mark.")
    return finish("pass")
