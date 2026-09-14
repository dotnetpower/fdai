"""Pinned telemetry replay contracts for one alert-evaluation treatment."""

from __future__ import annotations

from typing import Annotated, Self

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
        if self.accepted != improved:
            raise ValueError("evaluation acceptance contradicts measured counts")
        return self
