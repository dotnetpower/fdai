"""Provider-neutral observation seam for WAF and CAF assessment evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")


class FrameworkObservationOutcome(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FrameworkObservationRequest:
    framework_id: str
    catalog_digest: str
    scope_digest: str
    control_ids: tuple[str, ...]
    inventory_generation: str | None
    hierarchy_generation: str | None
    evaluated_at: datetime
    maximum_observations: int = 500
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if self.framework_id not in {"azure-waf", "azure-caf"}:
            raise ValueError("framework observation supports only azure-waf or azure-caf")
        for label, value in (
            ("catalog_digest", self.catalog_digest),
            ("scope_digest", self.scope_digest),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"framework observation {label} MUST be lowercase SHA-256")
        if not self.control_ids or self.control_ids != tuple(sorted(set(self.control_ids))):
            raise ValueError(
                "framework observation control ids MUST be non-empty, unique, and ordered"
            )
        if (self.inventory_generation is None) == (self.hierarchy_generation is None):
            raise ValueError("framework observation requires exactly one source generation")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("framework observation evaluated_at MUST be timezone-aware")
        if not 1 <= self.maximum_observations <= 2_000:
            raise ValueError("framework observation maximum_observations MUST be in [1, 2000]")
        if not 1 <= self.timeout_seconds <= 60:
            raise ValueError("framework observation timeout_seconds MUST be in [1, 60]")


@dataclass(frozen=True, slots=True)
class FrameworkProviderObservation:
    control_id: str
    requirement_ref: str
    evidence_ref: str
    evidence_kind: str
    producer: str
    source_identity: str
    observed_at: datetime
    recorded_at: datetime
    evidence_digest: str
    complete: bool
    truncated: bool
    conflicting: bool
    synthetic: bool
    provider_error: str | None
    outcome: FrameworkObservationOutcome

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.control_id,
                self.requirement_ref,
                self.evidence_ref,
                self.evidence_kind,
                self.producer,
                self.source_identity,
            )
        ):
            raise ValueError("framework provider observation identity fields MUST be non-empty")
        if _SHA256.fullmatch(self.evidence_digest) is None:
            raise ValueError("framework provider evidence digest MUST be lowercase SHA-256")
        if self.observed_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("framework provider observation timestamps MUST be timezone-aware")
        if self.recorded_at < self.observed_at:
            raise ValueError("framework provider recorded_at MUST follow observed_at")


@runtime_checkable
class FrameworkAssessmentObservationProvider(Protocol):
    """Return bounded read-only observations without assessment authority."""

    async def observe(
        self,
        request: FrameworkObservationRequest,
    ) -> tuple[FrameworkProviderObservation, ...]:
        """Return observations or raise a provider-specific availability error."""
        ...


__all__ = [
    "FrameworkAssessmentObservationProvider",
    "FrameworkObservationOutcome",
    "FrameworkObservationRequest",
    "FrameworkProviderObservation",
]
