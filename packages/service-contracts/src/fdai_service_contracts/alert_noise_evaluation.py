"""Pinned telemetry replay contracts for one alert-evaluation treatment."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from fdai_service_contracts.alert_noise import Count, Evaluation, Finite, Ref
from fdai_service_contracts.alert_noise_base import AlertContractBase as ContractBase
from fdai_service_contracts.alert_noise_base import AlertTime as AwareDatetime
from fdai_service_contracts.alert_noise_base import FalseOnly
from fdai_service_contracts.executor_models import Digest


class EvaluationSample(ContractBase):
    """One independently labeled telemetry bucket; not inferred from fired alerts."""

    ref: Ref
    observed_at: AwareDatetime
    values: Annotated[tuple[Finite, ...], Field(min_length=1, max_length=3600)]
    actionable: StrictBool
    label_source_ref: Ref
    label_revision: Digest
    complete: StrictBool
    window_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)]


class EvaluationScenarioSet(ContractBase):
    """Frozen same-exposure cohort with independently supplied labels."""

    rule_ref: Ref
    rule_revision: Digest
    source_ref: Ref
    reviewer_ref: Ref
    cutoff: AwareDatetime
    samples: Annotated[tuple[EvaluationSample, ...], Field(min_length=2, max_length=10000)]

    @model_validator(mode="after")
    def coverage(self) -> Self:
        if self.source_ref == self.reviewer_ref:
            raise ValueError("evaluation labels require an independent reviewer")
        if len({sample.ref for sample in self.samples}) != len(self.samples):
            raise ValueError("evaluation sample identities MUST be unique")
        if any(sample.observed_at > self.cutoff or not sample.complete for sample in self.samples):
            raise ValueError("evaluation samples MUST be complete and precede cutoff")
        if {sample.actionable for sample in self.samples} != {True, False}:
            raise ValueError("evaluation scenarios require positive and negative cases")
        return self


class EvaluationCaseResult(ContractBase):
    """Paired detection for one labeled temporal case; absence is never zero latency."""

    ref: Ref
    actionable: StrictBool
    baseline_detected: StrictBool
    treatment_detected: StrictBool
    baseline_latency_seconds: Count | None
    treatment_latency_seconds: Count | None

    @model_validator(mode="after")
    def latency_evidence(self) -> Self:
        for detected, latency in (
            (self.baseline_detected, self.baseline_latency_seconds),
            (self.treatment_detected, self.treatment_latency_seconds),
        ):
            if (latency is not None) != (self.actionable and detected):
                raise ValueError("latency requires a detected independently actionable case")
        return self

    @property
    def positive_regressed(self) -> bool:
        """Never exchange one lost or delayed positive for improvement on another case."""
        before, after = self.baseline_latency_seconds, self.treatment_latency_seconds
        return before is not None and (after is None or after > before)


class EvaluationReceipt(ContractBase):
    """Measured replay result bound to the exact target, baseline and treatment."""

    rule_ref: Ref
    rule_revision: Digest
    scenario_digest: Digest
    baseline: Evaluation
    treatment: Evaluation
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime
    baseline_true_positive: Count
    treatment_true_positive: Count
    baseline_false_positive: Count
    treatment_false_positive: Count
    baseline_false_negative: Count
    treatment_false_negative: Count
    accepted: StrictBool
    reason: Ref
    replay_method: Literal["same-bucket-threshold-v1", "uniform-metric-series-v1"] = (
        "same-bucket-threshold-v1"
    )
    baseline_max_latency_seconds: Count | None = None
    treatment_max_latency_seconds: Count | None = None
    case_results: Annotated[tuple[EvaluationCaseResult, ...], Field(max_length=128)] = ()
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def receipt_consistency(self) -> Self:
        if not 0 < (self.expires_at - self.evaluated_at).total_seconds() <= 3600:
            raise ValueError("evaluation receipt requires a bounded review validity")
        improved = (
            self.treatment_false_positive < self.baseline_false_positive
            and self.treatment_false_negative <= self.baseline_false_negative
            and self.treatment_true_positive >= self.baseline_true_positive
        )
        temporal = self.replay_method == "uniform-metric-series-v1"
        before, after = self.baseline_max_latency_seconds, self.treatment_max_latency_seconds
        if temporal:
            cases = self.case_results
            if {row.actionable for row in cases} != {False, True} or len(
                {row.ref for row in cases}
            ) != len(cases):
                raise ValueError(
                    "temporal replay requires unique paired positive and negative cases"
                )
            for prefix in ("baseline", "treatment"):
                actual = (
                    sum(row.actionable and getattr(row, f"{prefix}_detected") for row in cases),
                    sum(not row.actionable and getattr(row, f"{prefix}_detected") for row in cases),
                    sum(row.actionable and not getattr(row, f"{prefix}_detected") for row in cases),
                )
                if actual != (
                    getattr(self, f"{prefix}_true_positive"),
                    getattr(self, f"{prefix}_false_positive"),
                    getattr(self, f"{prefix}_false_negative"),
                ):
                    raise ValueError("temporal replay counts contradict paired cases")
                latencies = [
                    value
                    for row in cases
                    if (value := getattr(row, f"{prefix}_latency_seconds")) is not None
                ]
                if max(latencies, default=None) != getattr(self, f"{prefix}_max_latency_seconds"):
                    raise ValueError("temporal replay latency contradicts paired cases")
            improved = (
                improved
                and before is not None
                and after is not None
                and after <= before
                and not any(row.positive_regressed for row in cases)
            )
        elif before is not None or after is not None or self.case_results:
            raise ValueError("same-bucket replay MUST NOT claim temporal latency")
        if self.accepted != improved:
            raise ValueError("evaluation acceptance contradicts measured counts")
        return self


class EvaluationSeries(ContractBase):
    """One independent complete uniform metric scenario, including full warm-up.

    Each value represents one equally weighted native metric sample at the end of a
    declared interval. Aggregated, missing, censored or irregular samples are unsupported.
    Actionable onset is independently labeled, never inferred from detector firings.
    """

    ref: Ref
    starts_at: AwareDatetime
    sample_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)]
    values: Annotated[tuple[Finite, ...], Field(min_length=2, max_length=10000)]
    evaluation_start: AwareDatetime
    evaluation_end: AwareDatetime
    actionable_at: AwareDatetime | None
    label_source_ref: Ref
    label_revision: Digest
    complete: StrictBool

    @model_validator(mode="after")
    def timeline(self) -> Self:
        if not self.complete:
            raise ValueError("temporal replay MUST NOT score incomplete samples")
        if not self.starts_at < self.evaluation_start < self.evaluation_end:
            raise ValueError("evaluation series MUST include warm-up and a positive interval")
        duration = (self.evaluation_end - self.starts_at).total_seconds()
        if duration != self.sample_seconds * len(self.values):
            raise ValueError("evaluation series MUST cover every uniform sample interval")
        if self.actionable_at is not None and not (
            self.evaluation_start <= self.actionable_at < self.evaluation_end
        ):
            raise ValueError("actionable onset MUST be inside the scored interval")
        if (
            self.actionable_at is not None
            and (self.actionable_at - self.starts_at).total_seconds() % self.sample_seconds
        ):
            raise ValueError("actionable onset MUST align with native sample intervals")
        if (self.evaluation_start - self.starts_at).total_seconds() % self.sample_seconds:
            raise ValueError("scored interval MUST align with complete samples")
        return self


def evaluation_axis(baseline: Evaluation, treatment: Evaluation) -> str | None:
    """Return one supported changed axis, or None for mixed/unchanged detector semantics."""
    changed = [
        name
        for name, value in baseline.model_dump().items()
        if treatment.model_dump()[name] != value
    ]
    return (
        changed[0]
        if len(changed) == 1 and changed[0] in {"threshold", "window_seconds", "frequency_seconds"}
        else None
    )


def evaluation_method_matches(receipt: EvaluationReceipt) -> bool:
    """A temporal change requires temporal exposure and latency evidence, not bucket counts."""
    axis = evaluation_axis(receipt.baseline, receipt.treatment)
    return (axis == "threshold" and receipt.replay_method == "same-bucket-threshold-v1") or (
        axis in {"window_seconds", "frequency_seconds"}
        and receipt.replay_method == "uniform-metric-series-v1"
        and receipt.baseline_max_latency_seconds is not None
        and receipt.treatment_max_latency_seconds is not None
        and receipt.treatment_max_latency_seconds <= receipt.baseline_max_latency_seconds
    )


class TemporalEvaluationScenarioSet(ContractBase):
    """Frozen same-exposure uniform series for supported simple metric semantics only."""

    rule_ref: Ref
    rule_revision: Digest
    source_ref: Ref
    reviewer_ref: Ref
    cutoff: AwareDatetime
    series: Annotated[tuple[EvaluationSeries, ...], Field(min_length=2, max_length=128)]

    @model_validator(mode="after")
    def cohort(self) -> Self:
        if self.source_ref == self.reviewer_ref:
            raise ValueError("temporal replay requires an independent reviewer")
        if len({row.ref for row in self.series}) != len(self.series):
            raise ValueError("temporal replay scenario identities MUST be unique")
        if sum(len(row.values) for row in self.series) > 250000:
            raise ValueError("temporal replay exceeds its total sample budget")
        if any(row.evaluation_end > self.cutoff for row in self.series):
            raise ValueError("temporal replay samples MUST precede the cutoff")
        if {row.actionable_at is not None for row in self.series} != {False, True}:
            raise ValueError("temporal replay requires independent positive and negative cases")
        return self
