"""Deterministic eligibility policy for detector-created Incidents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fdai.shared.contracts.models import IncidentSeverity

from .workflow_support import detected_incident_correlation_keys, detected_incident_event_id

if TYPE_CHECKING:
    from .lifecycle import IncidentWorkflowResult
    from .workflow import IncidentLifecycleWorkflow

_SEVERITY_ALIASES: dict[str, IncidentSeverity] = {
    "critical": IncidentSeverity.SEV1,
    "sev1": IncidentSeverity.SEV1,
    "high": IncidentSeverity.SEV2,
    "sev2": IncidentSeverity.SEV2,
    "medium": IncidentSeverity.SEV3,
    "sev3": IncidentSeverity.SEV3,
    "low": IncidentSeverity.SEV4,
    "sev4": IncidentSeverity.SEV4,
    "info": IncidentSeverity.SEV5,
    "sev5": IncidentSeverity.SEV5,
}
_SEVERITY_RANK = {
    IncidentSeverity.SEV1: 1,
    IncidentSeverity.SEV2: 2,
    IncidentSeverity.SEV3: 3,
    IncidentSeverity.SEV4: 4,
    IncidentSeverity.SEV5: 5,
}


@dataclass(frozen=True, slots=True)
class IncidentAutoOpenPolicy:
    """Startup-bound ceiling for detector-created Incident records."""

    enabled: bool = True
    minimum_severity: IncidentSeverity = IncidentSeverity.SEV2

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled MUST be a boolean")
        if not isinstance(self.minimum_severity, IncidentSeverity):
            raise TypeError("minimum_severity MUST be an IncidentSeverity")


@dataclass(frozen=True, slots=True)
class IncidentAutoOpenDecision:
    """One explainable policy result; an ineligible result never writes."""

    eligible: bool
    reason: str
    severity: IncidentSeverity | None = None


def evaluate_incident_auto_open(
    candidate: Mapping[str, object],
    policy: IncidentAutoOpenPolicy,
) -> IncidentAutoOpenDecision:
    """Evaluate authority, evidence, and severity without side effects."""
    if not policy.enabled:
        return IncidentAutoOpenDecision(False, "auto_open_disabled")
    correlation_mode = _text(candidate, "incident_correlation").casefold()
    if correlation_mode != "correlate":
        return IncidentAutoOpenDecision(False, "incident_correlation_disabled")
    if not _text(candidate, "correlation_id"):
        return IncidentAutoOpenDecision(False, "correlation_missing")
    if not _text(candidate, "evidence_key"):
        return IncidentAutoOpenDecision(False, "evidence_missing")
    if not _text(candidate, "resource_id"):
        return IncidentAutoOpenDecision(False, "resource_missing")
    if not _text(candidate, "event_type"):
        return IncidentAutoOpenDecision(False, "event_type_missing")
    severity = incident_severity(candidate.get("severity"))
    if _SEVERITY_RANK[severity] > _SEVERITY_RANK[policy.minimum_severity]:
        return IncidentAutoOpenDecision(False, "severity_below_minimum", severity)
    return IncidentAutoOpenDecision(True, "eligible", severity)


def incident_severity(value: object) -> IncidentSeverity:
    """Normalize a recorded severity; unknown values stay conservative at SEV3."""
    normalized = str(value or "").strip().casefold()
    return _SEVERITY_ALIASES.get(normalized, IncidentSeverity.SEV3)


async def open_detected_incident_candidate(
    *,
    workflow: IncidentLifecycleWorkflow,
    candidate: Mapping[str, object],
    policy: IncidentAutoOpenPolicy,
) -> IncidentWorkflowResult | None:
    """Open one eligible detector candidate through the lifecycle authority."""
    decision = evaluate_incident_auto_open(candidate, policy)
    if not decision.eligible or decision.severity is None:
        return None
    resource_id = _text(candidate, "resource_id")
    event_type = _text(candidate, "event_type")
    return await workflow.open_from_agent(
        producer_principal="Heimdall",
        correlation_keys=detected_incident_correlation_keys(
            resource_id=resource_id,
            event_type=event_type,
            correlation_id=_text(candidate, "correlation_id"),
        ),
        severity=decision.severity,
        member_event_ids=(detected_incident_event_id(_text(candidate, "evidence_key")),),
        reason=_text(candidate, "reason_code") or "repeated_event_threshold",
    )


def _text(candidate: Mapping[str, object], key: str) -> str:
    value = candidate.get(key)
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "IncidentAutoOpenDecision",
    "IncidentAutoOpenPolicy",
    "evaluate_incident_auto_open",
    "incident_severity",
    "open_detected_incident_candidate",
]
