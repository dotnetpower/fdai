"""Replay simple metric evaluation on complete uniform samples with recall and latency guards."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import fsum

from fdai_service_contracts.alert_noise import Evaluation, digest_record
from fdai_service_contracts.alert_noise_evaluation import (
    EvaluationCaseResult,
    EvaluationReceipt,
    EvaluationSeries,
    TemporalEvaluationScenarioSet,
)


def _first_detection(series: EvaluationSeries, config: Evaluation) -> datetime | None:
    period = series.sample_seconds
    warmup = int((series.evaluation_start - series.starts_at).total_seconds())
    duration = int((series.evaluation_end - series.starts_at).total_seconds())
    if (
        config.window_seconds % period
        or config.frequency_seconds % period
        or warmup < config.window_seconds
        or config.frequency_seconds > config.window_seconds
    ):
        raise ValueError("temporal replay exposure or cadence is unsupported")
    width = config.window_seconds // period
    first = ((warmup + config.frequency_seconds - 1) // config.frequency_seconds) * (
        config.frequency_seconds
    )
    for elapsed in range(first, duration + 1, config.frequency_seconds):
        end = elapsed // period
        values = series.values[end - width : end]
        value = (
            fsum(item / len(values) for item in values)
            if config.aggregation == "average"
            else max(values)
            if config.aggregation == "maximum"
            else min(values)
        )
        fired = value > config.threshold if config.operator == "above" else value < config.threshold
        if fired:
            detected_at = series.starts_at + timedelta(seconds=elapsed)
            if series.actionable_at is not None and detected_at < series.actionable_at:
                raise ValueError("detector fires before the independently labeled actionable onset")
            return detected_at
    return None


def compare_temporal_evaluation(
    scenarios: TemporalEvaluationScenarioSet,
    *,
    baseline: Evaluation,
    treatment: Evaluation,
    now: datetime,
) -> EvaluationReceipt:
    """Compare one window/frequency axis; same samples never imply actual delivery or authority."""
    scenarios = TemporalEvaluationScenarioSet.model_validate(scenarios)
    baseline, treatment = Evaluation.model_validate(baseline), Evaluation.model_validate(treatment)
    changed = [
        key for key, value in baseline.model_dump().items() if treatment.model_dump()[key] != value
    ]
    if changed not in (["window_seconds"], ["frequency_seconds"]):
        raise ValueError("temporal replay requires exactly one window or frequency change")
    if now.tzinfo is None or now.utcoffset() is None or scenarios.cutoff > now:
        raise ValueError("temporal replay requires a current timezone-aware cutoff")
    work = sum(
        int(
            (series.evaluation_end - series.evaluation_start).total_seconds()
            // config.frequency_seconds
            + 1
        )
        * (config.window_seconds // series.sample_seconds)
        for series in scenarios.series
        for config in (baseline, treatment)
    )
    if work > 5_000_000:
        raise ValueError("temporal replay exceeds its finite computation budget")

    cases = []
    for series in scenarios.series:
        original = _first_detection(series, baseline)
        candidate = _first_detection(series, treatment)
        onset = series.actionable_at
        cases.append(
            EvaluationCaseResult(
                ref=series.ref,
                actionable=onset is not None,
                baseline_detected=original is not None,
                treatment_detected=candidate is not None,
                baseline_latency_seconds=int((original - onset).total_seconds())
                if original is not None and onset is not None
                else None,
                treatment_latency_seconds=int((candidate - onset).total_seconds())
                if candidate is not None and onset is not None
                else None,
            )
        )

    def counts(*, candidate: bool) -> tuple[int, int, int, int | None]:
        positives = false_positives = false_negatives = 0
        latencies: list[int] = []
        for row in cases:
            detected = row.treatment_detected if candidate else row.baseline_detected
            latency = row.treatment_latency_seconds if candidate else row.baseline_latency_seconds
            positives += int(row.actionable and detected)
            false_positives += int(not row.actionable and detected)
            false_negatives += int(row.actionable and not detected)
            if latency is not None:
                latencies.append(latency)
        return positives, false_positives, false_negatives, max(latencies, default=None)

    before, after = counts(candidate=False), counts(candidate=True)
    accepted = (
        after[1] < before[1]
        and after[2] <= before[2]
        and after[0] >= before[0]
        and before[3] is not None
        and after[3] is not None
        and after[3] <= before[3]
        and not any(row.positive_regressed for row in cases)
    )
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
        baseline_max_latency_seconds=before[3],
        treatment_max_latency_seconds=after[3],
        case_results=tuple(cases),
        replay_method="uniform-metric-series-v1",
        accepted=accepted,
        reason="improved_without_recall_or_latency_loss" if accepted else "guard_or_benefit_failed",
    )
