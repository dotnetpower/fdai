"""Normalized evidence inputs for deep security assessments.

Collectors translate vendor configuration, policy, vulnerability, and telemetry
records into these CSP-neutral shapes before the deterministic assessment fold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.shared.providers.projection import Severity


class ControlStatus(StrEnum):
    """Observed state of one security control."""

    PASS = "pass"  # noqa: S105 - control verdict, not a credential
    FAIL = "fail"
    WARNING = "warning"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    """Availability of one assessment data source."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ApplicabilityStatus(StrEnum):
    """Whether vulnerability or control evidence applies to the resource."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class RemediationPriority(StrEnum):
    """Operational ordering for a grounded recommendation."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SecurityControlObservation:
    """One grounded current-state control observation."""

    control_id: str
    title: str
    category: str
    resource_type: str
    resource_ref: str
    status: ControlStatus
    severity: Severity
    current_value: str
    expected_value: str
    rationale: str
    source: str
    collected_at: datetime
    evidence_refs: tuple[str, ...] = ()
    remediation: str = ""
    validation: str = ""
    priority: RemediationPriority = RemediationPriority.NONE
    due_days: int | None = None
    applicability: ApplicabilityStatus = ApplicabilityStatus.APPLICABLE
    cve_ids: tuple[str, ...] = ()
    compliance_controls: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()
    managed_service_note: str = ""
    patch_status: str = ""

    def __post_init__(self) -> None:
        required = (
            self.control_id,
            self.title,
            self.category,
            self.resource_type,
            self.resource_ref,
            self.source,
        )
        if any(not value.strip() for value in required):
            raise ValueError("SecurityControlObservation identity fields MUST be non-empty")
        if self.due_days is not None and self.due_days < 0:
            raise ValueError("SecurityControlObservation.due_days MUST be >= 0")
        if self.collected_at.utcoffset() is None:
            raise ValueError("SecurityControlObservation.collected_at MUST be timezone-aware")
        if not isinstance(self.applicability, ApplicabilityStatus):
            raise ValueError("SecurityControlObservation.applicability is invalid")


@dataclass(frozen=True, slots=True)
class SecuritySourceCoverage:
    """Coverage and freshness of one data source used by the assessment."""

    source: str
    status: SourceStatus
    record_count: int
    as_of: datetime | None = None
    scope: str = ""
    error: str = ""
    fresh: bool | None = None

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("SecuritySourceCoverage.source MUST be non-empty")
        if self.record_count < 0:
            raise ValueError("SecuritySourceCoverage.record_count MUST be >= 0")


@dataclass(frozen=True, slots=True)
class SecurityRecommendation:
    """Actionable recommendation derived only from an observed control."""

    control_id: str
    resource_ref: str
    priority: RemediationPriority
    severity: Severity
    action: str
    validation: str
    due_at: datetime | None
    evidence_refs: tuple[str, ...]


__all__ = [
    "ControlStatus",
    "ApplicabilityStatus",
    "RemediationPriority",
    "SecurityControlObservation",
    "SecurityRecommendation",
    "SecuritySourceCoverage",
    "SourceStatus",
]
