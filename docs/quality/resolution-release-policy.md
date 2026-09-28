# Resolution release policy

Policy ID: `resolution-quality-2026-09-28`

Written: **2026-09-28**, before the next measurement.

Applies to new or changed identity-resolution rules and their output arms.

This policy does not claim that the current changes have passed a fresh real-data
measurement. The checked-in aggregate template is deliberately **measurement_pending**.
Passing software tests is necessary, but is not a resolution-quality measurement.
The data owner retains the private sampling/grading tool and all real pairs.

## Fixed marks and their provenance

| Arm | Gate population | Required Wilson 95% lower bound | Minimum scored pairs | Provenance |
|---|---|---:|---:|---|
| Review queue | Representative sample of the whole queue produced by the candidate ruleset | 0.70 | 100 | Mark's existing standard, written 2026-09-10 before the measured rules; retained unchanged |
| Auto-merge | Each new or changed rule's own automatic-positive population | 0.99 | 400 per changed rule | **Our new conservative initial policy**, written 2026-09-28; not a number supplied or already accepted by Mark |

Review-queue per-rule results are **diagnostic only**. They do not inherit a 0.70
per-rule gate or a 100-pair per-rule minimum. Nevertheless, each changed rule must
have sampled positives and a reported breakdown: a rule with no sampled output is
unmeasured, not validated by other rules' successes. The automatic arm has a separate
per-rule gate so that pooling cannot hide an unsafe automatic rule.

These are precision marks conditional on adjudicable pairs, not an assertion about
the correctness of unknown pairs. No retrospective unknown-rate cutoff is invented
here. Every decision must display the unknown rate prominently; high unknown rates
limit what the precision estimate establishes and warrant a rule/evidence redesign.
Any additional numerical unknown-rate requirement must be preregistered for a fresh
measurement, never fitted to results already inspected.

The marks do not move after results are known. A failing rule changes, remains
unreleased, or is proposed for review-only operation. Moving from auto-merge to the
review queue still requires the queue arm's measurement; it is not an automatic
quality exemption. A safety retirement can merge before replacement-quality
acceptance, but removing a bad rule from an old sample is not a fresh measurement.
The unchanged minimum sample size still applies even if a retrospective lower bound
exceeds 0.70.

This change does not silently disable every pre-existing unmeasured automatic rule.
It establishes the explicit promotion check for subsequent changed-rule releases;
the absence of automatic outputs so far is absence of measurement, not proof of safety.

## Register before drawing or inspecting the holdout

Commit a preregistration record containing:

1. Policy ID, intended arm, changed rule names, complete code commit and immutable
   ruleset/configuration version. Each rule's version must be reported after grading.
2. A timestamp with timezone, the population window and eligibility criteria,
   sampling unit, sample-size plan, random selection method, and stopping rule.
3. An opaque holdout identifier; a declaration that this cohort has not been used to
   tune the changed rule, its thresholds, or the sampling plan.

Use the commit that contains the preregistration as `preregistration.commit` in the
later aggregate attestation. It must precede sampling and inspection of outcomes.
Record the target code commit separately: the preregistration commit need not be the
code commit. The release owner verifies the commit contents and chronology.
The checker validates the supplied identifiers, timestamps, and declarations; it
cannot prove private sampling integrity or remote Git history from aggregate JSON.

The sample comes from the rule's **own positives**: proposed review candidates for
the queue arm, or would-auto-merge candidates under the exact candidate rule/config
for the automatic arm. Automatic positives may be captured in a non-mutating shadow
run; an unvalidated rule need not fuse live identities to obtain a sample.
Do not curate easy pairs or sample only cases another rule approved.

For the review gate, use a uniform/otherwise representative sample of the entire
candidate queue under the release ruleset. A convenient balanced sample per rule,
pooled without adjustment, is not representative of the queue mixture and cannot
use this simple binomial Wilson gate. Do not count duplicate appearances of one pair
as independent observations; preregister deduplication and multi-rule attribution.
If dependency between pairs is material, disclose the limitation and preregister a
sampling design addressing it rather than implying Wilson corrects dependence.

The grader must not see the rule name, score, system decision, or whether the pair
was slated for automatic merging or review. Record same/different/unknown first;
join the private rule/version attribution **after** adjudication. Preserve all
sampled unknowns. A new rule revision uses a fresh holdout. Do not repeatedly test
the same cohort, or keep extending it until the lower bound happens to pass.

## Aggregate-only contract and calculation

Use [resolution-measurement.template.json](resolution-measurement.template.json)
and [resolution-measurement.schema.json](resolution-measurement.schema.json).
Null metadata/measurement in the starter template is intentional. Do not fill it
with illustrative numbers and present them as observed results.

`preregistration` contains `commit`, `registered_at`, `sampling_plan`, `holdout_id`.
`measurement` contains `sampled_at`, `graded_at`, `fresh_holdout`,
`blind_to_rule_and_decision`, `own_positives`, `representative_queue_sample`, and
`same`, `different`, `unknown`. `by_rule` contains the same counts plus `rule` and
`rule_version` for every attributed rule, with no duplicates. Those counts must sum
exactly to the whole-arm counts. For auto-merge, `representative_queue_sample` is
false because the population is each changed automatic rule's positives.

For counts S=same, D=different, U=unknown:

```text
scored n = S + D
sampled total = S + D + U
precision p = S / n                       (undefined if n = 0)
unknown rate = U / (S + D + U)             (undefined if total = 0)
z = 1.959963984540054
Wilson lower = [p + z²/(2n) - z sqrt(p(1-p)/n + z²/(4n²))] / [1 + z²/n]
```

This is the lower endpoint of the **two-sided 95%** Wilson interval, not the
one-sided 95% bound. Use full precision in comparisons; round only display values.
Unknowns remain in the reported sample total and unknown-rate denominator; they
are neither silently discarded from reporting nor counted as successful matches.
With no scored pairs, the bound is undefined and the result cannot pass.

Synthetic mathematical examples (not measurements): 99 same out of 100 scored has
a lower bound of 0.945513803821; 400/400 has 0.990487705666, while 399/400 fails
the 0.99 bound. Even 60/60 cannot satisfy a minimum of 100 scored pairs.

No real pair IDs, names, handles, addresses, message text, evidence excerpts,
database exports, grading sheets, or private-tool implementation belong in this
public repository. Store raw data and the holdout ledger privately with the data
owner. Only explicitly approved aggregate attestations may be published; the
checker may consume an aggregate file outside the checkout, so publication is not
required for running the check. Opaque IDs must not encode personal information.

## Explicit release command

From the repository root, after supplying a completed aggregate attestation:

```powershell
python -m scripts.check_resolution_quality "path/to/aggregate.json" --expected-code-version <full-target-commit> --expected-ruleset-version <immutable-ruleset-version>
```

Use the intended release commit/config, not values copied uncritically from an old
attestation. The command loads no database, credentials, environment file, private
pairs, or grading tool, and it performs no merges. It returns JSON with both scored
and total denominators, the unknown rate, lower bound, and per-rule diagnostics.

| Exit | Status | Meaning |
|---:|---|---|
| 0 | `pass` | Complete matching attestation meets the arm's fixed numerical gate |
| 1 | `fail` | Sufficient scored observations, lower bound misses the mark |
| 2 | `measurement_pending` | Missing preregistration/measurement, missing changed-rule positives, or insufficient scored observations |
| 3 | `invalid` | Invalid/inconsistent counts, version mismatch, bad chronology, or unsupported sampling/blinding declarations |

The command only sets `promotable: true` for exit 0. A release owner must run this
check for a changed rule and retain its result together with the verified
preregistration. It is an **explicit release gate**, not currently wired into CI or
runtime and not a cryptographic attestation of honest grading. Software fixes can
be reviewed and merged while fresh quality acceptance remains pending; no green CI
badge or empty historical merge log substitutes for that acceptance.

## Current acceptance state

No fresh real-data sample has been supplied for this revision. Quality acceptance
therefore remains **measurement_pending**. The data owner will draw a new holdout
after the rule changes; the aggregate result can then be checked without importing
the private tool or real pairs. Until then, report implementation/test results and
quality-measurement status separately.
