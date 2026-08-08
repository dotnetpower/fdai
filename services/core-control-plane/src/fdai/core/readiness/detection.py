"""Deterministic readiness reduction for monitored workload targets."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from fdai.core.readiness.models import AuthorityCeiling, more_restrictive
from fdai.shared.contracts.models import ContractBase

DETECTION_READINESS_STATE_PREFIX = "runtime:detection-readiness:"


class DetectionReadinessDimension(StrEnum):
    DISCOVERED = "discovered"
    COLLECTOR_CONFIGURED = "collector_configured"
    TELEMETRY_OBSERVED = "telemetry_observed"
    DETECTOR_BOUND = "detector_bound"
    PIPELINE_OBSERVED = "pipeline_observed"
    ACTION_GOVERNED = "action_governed"


class DetectionObservationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"


class DetectionReadinessDecision(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    STALE = "stale"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN = "unknown"


class DetectionReadinessObservation(ContractBase):
    """One sanitized fact observed by an external mechanical probe."""

    resource_ref: Annotated[str, Field(min_length=1, max_length=512)]
    dimension: DetectionReadinessDimension
    status: DetectionObservationStatus
    observed_at: datetime
    expires_at: datetime
    source: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
    evidence_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    detail_code: Annotated[
        str | None,
        Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$"),
    ] = None

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("detection readiness timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_observation(self) -> DetectionReadinessObservation:
        if self.expires_at <= self.observed_at:
            raise ValueError("detection readiness expiry MUST follow observation time")
        if self.status is DetectionObservationStatus.PASSED and self.detail_code is not None:
            raise ValueError("passed detection observations MUST NOT include a detail code")
        if self.status is not DetectionObservationStatus.PASSED and self.detail_code is None:
            raise ValueError("non-passing detection observations MUST include a detail code")
        return self


class DetectionReadinessSnapshot(ContractBase):
    """Agent-owned reduction of the latest evidence for one target."""

    resource_ref: Annotated[str, Field(min_length=1, max_length=512)]
    generated_at: datetime
    decision: DetectionReadinessDecision
    observations: tuple[DetectionReadinessObservation, ...]
    missing_dimensions: tuple[DetectionReadinessDimension, ...] = ()
    stale_dimensions: tuple[DetectionReadinessDimension, ...] = ()
    authority_ceiling: AuthorityCeiling

    @field_validator("generated_at")
    @classmethod
    def require_generated_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("detection readiness generation time MUST be timezone-aware")
        return value


def reduce_detection_readiness(
    observations: tuple[DetectionReadinessObservation, ...],
    *,
    resource_ref: str,
    generated_at: datetime,
    deployment_ceiling: AuthorityCeiling = AuthorityCeiling.DEPLOYMENT,
) -> DetectionReadinessSnapshot:
    """Reduce one target's latest dimension evidence without raising authority."""

    relevant = tuple(item for item in observations if item.resource_ref == resource_ref)
    by_dimension = {item.dimension: item for item in relevant}
    if len(by_dimension) != len(relevant):
        raise ValueError("detection readiness observations MUST be unique by dimension")

    required = tuple(DetectionReadinessDimension)
    missing = tuple(item for item in required if item not in by_dimension)
    stale = tuple(item.dimension for item in relevant if item.expires_at <= generated_at)
    current = tuple(item for item in relevant if item.dimension not in stale)
    statuses = {item.status for item in current}

    if DetectionObservationStatus.UNAUTHORIZED in statuses:
        decision = DetectionReadinessDecision.UNAUTHORIZED
    elif DetectionObservationStatus.FAILED in statuses:
        decision = DetectionReadinessDecision.BLOCKED
    elif stale:
        decision = DetectionReadinessDecision.STALE
    elif not relevant:
        decision = DetectionReadinessDecision.UNKNOWN
    elif missing or DetectionObservationStatus.UNAVAILABLE in statuses:
        decision = DetectionReadinessDecision.PARTIAL
    else:
        decision = DetectionReadinessDecision.READY

    ceiling = deployment_ceiling
    if decision is not DetectionReadinessDecision.READY:
        ceiling = more_restrictive(ceiling, AuthorityCeiling.SHADOW)

    return DetectionReadinessSnapshot(
        resource_ref=resource_ref,
        generated_at=generated_at,
        decision=decision,
        observations=tuple(sorted(relevant, key=lambda item: item.dimension.value)),
        missing_dimensions=missing,
        stale_dimensions=tuple(sorted(stale, key=lambda item: item.value)),
        authority_ceiling=ceiling,
    )


def detection_readiness_state_key(resource_ref: str) -> str:
    """Return a stable state key without exposing the resource ref in the key."""
    if not resource_ref:
        raise ValueError("detection readiness resource_ref MUST be non-empty")
    digest = hashlib.sha256(resource_ref.encode("utf-8")).hexdigest()
    return f"{DETECTION_READINESS_STATE_PREFIX}{digest}"


__all__ = [
    "DETECTION_READINESS_STATE_PREFIX",
    "DetectionObservationStatus",
    "DetectionReadinessDecision",
    "DetectionReadinessDimension",
    "DetectionReadinessObservation",
    "DetectionReadinessSnapshot",
    "detection_readiness_state_key",
    "reduce_detection_readiness",
]
