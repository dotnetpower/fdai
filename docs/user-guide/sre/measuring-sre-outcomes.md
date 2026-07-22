---
title: Measuring SRE Outcomes
description: How to measure FDAI SRE outcomes against paired baselines without mistaking automation volume for reliability.
---

# Measuring SRE Outcomes

FDAI measures SRE improvement through outcomes and guard metrics, not through
the percentage of decisions made automatically. Every comparison uses the same
scenario set, a stated measurement window, and paired baseline and treatment
evidence.

## Outcome metrics

| Metric | What it answers |
|--------|-----------------|
| MTTR distribution | How long resolution takes at the mean, median, and p90 |
| Auto-resolution rate | Which events reached the correct terminal outcome with no human touchpoint and no later rollback |
| Human touchpoints | How much operator work remains per incident |
| Change lead time | How long a governed change takes from request to merge |
| Cost per resolved event | What attributable platform and inference spend each result consumed |

## Guard metrics

Track change-failure rate, false positives, false negatives, rollback rate,
policy-violation escapes, audit gaps, verifier failures, and mixed-model
disagreement. An outcome improvement does not count if a guard metric regresses
past its threshold.

## Measurement contract

1. Freeze the scenario-set version and input distribution.
2. Record the baseline model, rules, thresholds, adapters, and catalog versions.
3. Run treatment against the same scenarios and observation window.
4. Report sample size, missing data, confidence, and distribution, not only an average.
5. Keep shadow and enforce outcomes separate.
6. Demote a capability when measured guard metrics regress.

## Avoid misleading claims

- Do not claim a multiplier without paired measurements.
- Do not treat a missing projection as zero.
- Do not merge mean and p90 into one latency statement.
- Do not count a later rollback as successful auto-resolution.
- Do not compare different scenario sets without labeling the change.

## Next steps

| To learn about | Read |
|----------------|------|
| Canonical formulas and windows | [Goals and metrics](../../roadmap/architecture/goals-and-metrics.md) |
| The named scenario sets and evidence levels | [Scenario validation inventory](scenario-validation-inventory.md) |
| How SLO burn measures workload impact | [SLOs and error budgets](slos-and-error-budgets.md) |
| How shadow evidence controls promotion | [Observe, then enable changes](../concepts/shadow-then-enforce.md) |
| How audit evidence is reconstructed | [Read the audit log](../guides/read-audit-log.md) |
