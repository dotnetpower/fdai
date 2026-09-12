"""Expiring, authority-free dashboard comparison over one admitted cohort context."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.baseline_cohort import (
    MINIMUM_COHORT_SAMPLE_SIZE,
    CohortArm,
    CohortGuardOutcome,
    CohortMetricEstimate,
    CommitRevision,
)
from fdai_service_contracts.executor_models import ContractBase, Digest, SemVer
from fdai_service_contracts.measurement_time import measurement_timestamp_input
from fdai_service_contracts.ontology_query import content_digest

DASHBOARD_COMPARISON_STATE_KEY = "measurement:dashboard-comparison:v1"
DASHBOARD_COMPARISON_ACTION_KIND = "measurement.dashboard_comparison.v1"


class DashboardComparisonArm(ContractBase):
    """Absolute cohort values and their evidence window, never rolling live values."""

    arm: CohortArm
    sample_count: int = Field(strict=True, ge=MINIMUM_COHORT_SAMPLE_SIZE, le=1_000_000)
    metrics: Annotated[tuple[CohortMetricEstimate, ...], Field(min_length=1, max_length=32)]
    guards: Annotated[tuple[CohortGuardOutcome, ...], Field(min_length=1, max_length=32)]
    report_digest: Digest
    provenance_digest: Digest
    evidence_receipt_digest: Digest
    window_basis: Literal["evidence_event_to_cutoff"] = "evidence_event_to_cutoff"
    window_start: datetime
    window_end: datetime

    @field_validator("window_start", "window_end", mode="before")
    @classmethod
    def _timestamp_shape(cls, value: object) -> object:
        return _timestamp_input(value)

    @field_validator("window_start", "window_end")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _validate_arm(self) -> DashboardComparisonArm:
        if self.window_start > self.window_end:
            raise ValueError("comparison evidence window is reversed")
        for identifiers in (
            tuple(metric.metric_id for metric in self.metrics),
            tuple(guard.guard_id for guard in self.guards),
        ):
            if identifiers != tuple(sorted(set(identifiers))):
                raise ValueError("comparison measures MUST be unique and ordered")
        if any(
            metric.sample_size < self.sample_count or metric.confidence_level_basis_points != 9_500
            for metric in self.metrics
        ):
            raise ValueError("comparison intervals MUST cover the retained cohort")
        if any(
            metric.metric_id == "auto_resolution_rate" and metric.upper_bound > 1
            for metric in self.metrics
        ):
            raise ValueError("auto-resolution comparison intervals MUST remain in [0, 1]")
        if any(
            guard.breached
            or guard.observed_basis_points != 0
            or guard.sample_size < self.sample_count
            for guard in self.guards
        ):
            raise ValueError("comparison guard evidence is incomplete or breached")
        if self.sample_count != min(
            *(metric.sample_size for metric in self.metrics),
            *(guard.sample_size for guard in self.guards),
        ):
            raise ValueError("comparison sample count MUST match its effective sample floor")
        return self


class _DashboardComparisonBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    cohort_id: Annotated[str, Field(min_length=1, max_length=256)]
    cohort_receipt_digest: Digest
    cohort_admission_receipt_digest: Digest
    measurement_protocol_version: SemVer
    measurement_protocol_digest: Digest
    fdai_revision: CommitRevision
    baseline: DashboardComparisonArm
    treatment: DashboardComparisonArm
    evidence_cutoff: datetime
    published_at: datetime
    valid_until: datetime
    admission_receipt_refs: Annotated[tuple[Digest, ...], Field(min_length=3, max_length=3)]
    verification_bundle_refs: Annotated[tuple[Digest, ...], Field(min_length=1, max_length=3)]
    artifact_origin: Literal["governed_external"] = "governed_external"
    synthetic: bool = Field(default=False, strict=True)
    execution_authority: bool = Field(default=False, strict=True)
    promotion_authority: bool = Field(default=False, strict=True)

    @field_validator("evidence_cutoff", "published_at", "valid_until", mode="before")
    @classmethod
    def _timestamp_shape(cls, value: object) -> object:
        return _timestamp_input(value)

    @field_validator("evidence_cutoff", "published_at", "valid_until")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _validate_context(self) -> _DashboardComparisonBody:
        if self.synthetic or self.execution_authority or self.promotion_authority:
            raise ValueError("dashboard comparisons MUST be non-synthetic and authority-free")
        if (
            self.baseline.arm is not CohortArm.BASELINE
            or self.treatment.arm is not CohortArm.TREATMENT
        ):
            raise ValueError("comparison arms are mislabeled")
        if not self.evidence_cutoff <= self.published_at < self.valid_until:
            raise ValueError("comparison publication lifetime is invalid")
        if self.evidence_cutoff != max(self.baseline.window_end, self.treatment.window_end):
            raise ValueError("comparison cutoff MUST match its latest arm evidence")
        if tuple(metric.metric_id for metric in self.baseline.metrics) != tuple(
            metric.metric_id for metric in self.treatment.metrics
        ):
            raise ValueError("comparison arms MUST contain matching metrics")
        if tuple(guard.guard_id for guard in self.baseline.guards) != tuple(
            guard.guard_id for guard in self.treatment.guards
        ):
            raise ValueError("comparison arms MUST contain matching guards")
        expected = {
            self.cohort_admission_receipt_digest,
            self.baseline.evidence_receipt_digest,
            self.treatment.evidence_receipt_digest,
        }
        if len(expected) != 3 or tuple(sorted(expected)) != self.admission_receipt_refs:
            raise ValueError("comparison MUST cite the three distinct admitted receipts")
        if tuple(sorted(set(self.verification_bundle_refs))) != self.verification_bundle_refs:
            raise ValueError("comparison verification bundles MUST be unique and ordered")
        if (
            self.baseline.report_digest == self.treatment.report_digest
            or self.baseline.provenance_digest == self.treatment.provenance_digest
        ):
            raise ValueError("comparison arms MUST use distinct report and provenance evidence")
        return self


class DashboardComparisonSnapshot(_DashboardComparisonBody):
    """One sealed publication, kept separate from rolling live KPI observations.

    Only the protected Core publisher constructs this record after current cohort
    admission. The digest validates content, not source authenticity. Readers use
    the Core-owned state projection and reject an expired snapshot rather than
    attaching its baseline to unrelated live metrics.
    """

    publication_id: Digest

    @model_validator(mode="after")
    def _validate_digest(self) -> DashboardComparisonSnapshot:
        if self.publication_id != content_digest(
            self.model_dump(mode="json", exclude={"publication_id"})
        ):
            raise ValueError("comparison publication digest does not match its content")
        return self

    @classmethod
    def from_state(
        cls, value: Mapping[str, object], *, evaluated_at: datetime
    ) -> DashboardComparisonSnapshot:
        """Parse the exact fixed-key state value and reject expired/future publications."""

        if set(value) != {"revision", "snapshot"}:
            raise ValueError("comparison state wrapper is invalid")
        revision = value["revision"]
        if type(revision) is not int or revision < 1:
            raise ValueError("comparison state revision MUST be a positive integer")
        raw = value["snapshot"]
        if not isinstance(raw, Mapping) or set(raw) != set(cls.model_fields):
            raise ValueError("comparison snapshot fields are incomplete or unknown")
        snapshot = cls.model_validate(raw)
        now = _aware_utc(evaluated_at)
        if not snapshot.published_at <= now < snapshot.valid_until:
            raise ValueError("comparison publication is not current")
        return snapshot


def dashboard_comparison_id(**values: object) -> str:
    """Seal the complete publication, including expiry and both retained arms."""

    body = dict(values)
    body.pop("publication_id", None)
    candidate = _DashboardComparisonBody.model_validate(body)
    return content_digest(candidate.model_dump(mode="json"))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("comparison timestamps MUST include a timezone")
    return value.astimezone(UTC)


def _timestamp_input(value: object) -> object:
    return measurement_timestamp_input(value)
