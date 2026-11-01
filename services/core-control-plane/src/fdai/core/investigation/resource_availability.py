"""Observation-only ResourceAnalyzer over declared policy and inventory evidence."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.investigation.contract import AnalyzerFinding, FindingAssessment
from fdai.core.investigation.resource_availability_evidence import (
    RESOURCE_AVAILABILITY_ASSESSOR,
    ResourceAvailabilityEvidence,
    ResourceAvailabilityPolicy,
    assess_resource_availability,
)
from fdai.shared.contracts.models import Severity

SIGNAL_RESOURCE_AVAILABILITY = "resource_availability"


class ResourceAvailabilityEvidenceSource(Protocol):
    async def observe(
        self, *, resource_ref: str, since: datetime, until: datetime
    ) -> ResourceAvailabilityEvidence: ...


class ResourceAvailabilityAnalyzer:
    """Only faults/gaps become Findings; recovery always binds a prior actual fault."""

    def __init__(
        self,
        *,
        resource_kind: str,
        resource_type: str,
        scope_ref: str,
        source: ResourceAvailabilityEvidenceSource,
        policy: ResourceAvailabilityPolicy,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not resource_kind.strip() or not resource_type.strip() or not scope_ref.strip():
            raise ValueError("availability analyzer MUST bind kind, type and scope")
        self._kind = resource_kind.strip()
        self._type = resource_type.strip()
        self._scope = scope_ref.strip()
        self._source = source
        self._policy = policy
        self._clock = wall_clock or (lambda: datetime.now(UTC))

    @property
    def resource_kind(self) -> str:
        return self._kind

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        return await self._analyze(resource_ref=resource_ref, window_seconds=window_seconds)

    async def analyze_recovery(
        self,
        *,
        prior_finding: AnalyzerFinding,
        finding_ref: str,
        window_seconds: float,
    ) -> Sequence[AnalyzerFinding]:
        """Caller supplies an active durable Finding, never an inferred absence."""

        if (
            not finding_ref.strip()
            or prior_finding.resource_kind != self._kind
            or prior_finding.signal != SIGNAL_RESOURCE_AVAILABILITY
            or prior_finding.assessment is None
            or prior_finding.assessment.assessed_by != RESOURCE_AVAILABILITY_ASSESSOR
            or prior_finding.assessment.recovery_closed is True
            or not prior_finding.assessment.evidence_complete
            or prior_finding.assessment.status
            not in {
                "stop_observed",
                "expected_running_not_observed",
                "expected_stop_not_observed",
            }
        ):
            raise ValueError("availability recovery MUST reference a prior actual fault Finding")
        return await self._analyze(
            resource_ref=prior_finding.resource_ref,
            window_seconds=window_seconds,
            prior_finding=prior_finding,
            finding_ref=finding_ref,
        )

    async def _analyze(
        self,
        *,
        resource_ref: str,
        window_seconds: float,
        prior_finding: AnalyzerFinding | None = None,
        finding_ref: str | None = None,
    ) -> Sequence[AnalyzerFinding]:
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("availability window MUST be finite and positive")
        until = self._clock()
        since = until - timedelta(seconds=window_seconds)
        evidence = await self._source.observe(resource_ref=resource_ref, since=since, until=until)
        assessment = assess_resource_availability(
            evidence,
            resource_ref=resource_ref,
            resource_type=self._type,
            scope_ref=self._scope,
            since=since,
            until=until,
            policy=self._policy,
            prior_status=prior_finding.assessment.status
            if prior_finding is not None and prior_finding.assessment is not None
            else None,
            prior_fault_at=prior_finding.occurred_at if prior_finding else None,
            prior_finding_ref=finding_ref,
        )
        if prior_finding is None and assessment.status in {
            "running_observed",
            "planned_stop_observed",
            "maintenance_stop_observed",
            "expected_stop_observed",
            "not_monitored",
        }:
            return ()
        mismatch = assessment.status in {
            "expected_running_not_observed",
            "expected_stop_not_observed",
        }
        severity = Severity.HIGH if mismatch else Severity.LOW
        if assessment.status == "stop_observed":
            severity = Severity.MEDIUM
        replay = {
            "evidence": asdict(evidence),
            "policy": {
                **asdict(self._policy),
                "resource_types": sorted(self._policy.resource_types),
            },
            "resource_ref": resource_ref,
            "resource_type": self._type,
            "scope_ref": self._scope,
            "since": since,
            "until": until,
            "prior_status": prior_finding.assessment.status
            if prior_finding is not None and prior_finding.assessment is not None
            else None,
            "prior_fault_at": prior_finding.occurred_at if prior_finding else None,
            "prior_finding_ref": finding_ref,
        }
        refs = tuple(
            ref
            for ref in (
                evidence.evidence_ref,
                self._policy.expectation_ref,
                finding_ref,
                *(window.evidence_ref for window in self._policy.planned_stops),
            )
            if ref
        )
        return (
            AnalyzerFinding(
                resource_ref=resource_ref,
                resource_kind=self._kind,
                signal=SIGNAL_RESOURCE_AVAILABILITY,
                observation=(
                    f"Resource operational-state assessment: {assessment.status}. "
                    "This observation does not establish a failure cause or authorize an action."
                ),
                severity=severity,
                occurred_at=(evidence.observed_at if assessment.evidence_complete else until)
                or until,
                evidence_refs=tuple(dict.fromkeys(refs)),
                assessment=FindingAssessment(
                    assessed_by=RESOURCE_AVAILABILITY_ASSESSOR,
                    **asdict(assessment),
                ),
                metadata={
                    "assessment_input": json.dumps(
                        replay,
                        default=lambda value: value.isoformat(),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                },
            ),
        )
