"""Deterministic same-bucket threshold replay; unsupported semantic changes stay held."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import fsum

from fdai_service_contracts.alert_noise import Evaluation, digest_record
from fdai_service_contracts.alert_noise_evaluation import EvaluationReceipt, EvaluationScenarioSet


def compare_evaluation(
    scenarios: EvaluationScenarioSet,
    *,
    baseline: Evaluation,
    treatment: Evaluation,
    now: datetime,
) -> EvaluationReceipt:
    """Compare a threshold change without guessing a provider's window/frequency semantics."""
    if now.tzinfo is None or scenarios.cutoff > now:
        raise ValueError("evaluation cutoff MUST precede a timezone-aware review")
    if baseline.model_dump(exclude={"threshold"}) != treatment.model_dump(exclude={"threshold"}):
        raise ValueError("only same-bucket threshold comparisons are supported")
    if any(sample.window_seconds != baseline.window_seconds for sample in scenarios.samples):
        raise ValueError("evaluation sample exposure MUST match the configured window")

    def counts(config: Evaluation) -> tuple[int, int, int]:
        true_positive = false_positive = false_negative = 0
        for sample in scenarios.samples:
            if config.aggregation == "average":
                value = fsum(number / len(sample.values) for number in sample.values)
            elif config.aggregation == "maximum":
                value = max(sample.values)
            else:
                value = min(sample.values)
            fired = (
                value > config.threshold if config.operator == "above" else value < config.threshold
            )
            true_positive += int(fired and sample.actionable)
            false_positive += int(fired and not sample.actionable)
            false_negative += int(not fired and sample.actionable)
        return true_positive, false_positive, false_negative

    before, after = counts(baseline), counts(treatment)
    accepted = after[1] < before[1] and after[2] <= before[2] and after[0] >= before[0]
    return EvaluationReceipt(
        rule_ref=scenarios.rule_ref,
        rule_revision=scenarios.rule_revision,
        scenario_digest=digest_record(scenarios),
        baseline=baseline,
        treatment=treatment,
        evaluated_at=now,
        expires_at=now + timedelta(hours=1),
        baseline_true_positive=before[0],
        treatment_true_positive=after[0],
        baseline_false_positive=before[1],
        treatment_false_positive=after[1],
        baseline_false_negative=before[2],
        treatment_false_negative=after[2],
        accepted=accepted,
        reason="improved_without_recall_loss" if accepted else "guard_or_benefit_failed",
    )
