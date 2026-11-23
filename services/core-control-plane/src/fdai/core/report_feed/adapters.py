"""Pure converters - module outputs -> normalized report signals.

Turns the outputs of the investigation, chaos, and IRP modules into
:class:`ReportSignal` values for the report feed. Deterministic and
I/O-free so "this outcome produces these signals" is exhaustively testable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC

from fdai.core.chaos.contract import ExperimentOutcome, ExperimentResult
from fdai.core.investigation.contract import InvestigationReport, Priority
from fdai.core.irp.coordinator import IrpOutcome, IrpResult
from fdai.core.ontology_platform.service_health_queries import ServiceHealthCollection
from fdai.core.report_feed.models import (
    ReportCategory,
    ReportSignal,
    SignalKind,
    severity_rank,
)
from fdai.shared.contracts.models import Severity

_PRIORITY_TO_SEVERITY: dict[Priority, Severity] = {
    Priority.P1: Severity.CRITICAL,
    Priority.P2: Severity.HIGH,
    Priority.P3: Severity.MEDIUM,
}

_CHAOS_OUTCOME_SEVERITY: dict[ExperimentOutcome, Severity] = {
    ExperimentOutcome.ROLLBACK_FAILED: Severity.CRITICAL,
    ExperimentOutcome.NOT_DETECTED: Severity.HIGH,
    ExperimentOutcome.ABORTED: Severity.MEDIUM,
    ExperimentOutcome.BLAST_RADIUS_EXCEEDED: Severity.MEDIUM,
    ExperimentOutcome.VALIDATED: Severity.LOW,
    ExperimentOutcome.SHADOWED: Severity.LOW,
}

_IRP_OUTCOME_SEVERITY: dict[IrpOutcome, Severity] = {
    IrpOutcome.APPROVED: Severity.HIGH,
    IrpOutcome.PENDING_APPROVAL: Severity.HIGH,
    IrpOutcome.REJECTED: Severity.MEDIUM,
    IrpOutcome.TIMEOUT: Severity.HIGH,
    IrpOutcome.NO_FINDING: Severity.LOW,
}


def signals_from_investigation(report: InvestigationReport) -> list[ReportSignal]:
    """One workload signal per investigation finding."""
    return [
        ReportSignal(
            signal_id=f"{report.investigation_id}:{i}",
            kind=SignalKind.INVESTIGATION,
            category=ReportCategory.WORKLOAD,
            severity=finding.severity,
            resource_ref=finding.resource_ref,
            title=f"[{finding.resource_kind}] {finding.signal}",
            detail=finding.observation,
            occurred_at=finding.occurred_at,
            evidence_refs=finding.evidence_refs,
        )
        for i, finding in enumerate(report.findings)
    ]


def signal_from_experiment(result: ExperimentResult) -> ReportSignal:
    """One workload signal summarizing a chaos experiment outcome."""
    severity = _CHAOS_OUTCOME_SEVERITY.get(result.outcome, Severity.MEDIUM)
    return ReportSignal(
        signal_id=result.experiment_id,
        kind=SignalKind.CHAOS,
        category=ReportCategory.WORKLOAD,
        severity=severity,
        resource_ref=", ".join(result.targets) if result.targets else "-",
        title=f"chaos {result.scenario_id}: {result.outcome.value}",
        detail=(
            f"expected_signal={result.expected_signal}; "
            f"detected={result.detected}; reverted={result.reverted}"
        ),
        occurred_at=result.ended_at,
        evidence_refs=(result.scenario_id,),
        metadata={
            "scenario_id": result.scenario_id,
            "outcome": result.outcome.value,
            "mode": result.mode.value,
            "expected_signal": result.expected_signal,
            "detected": str(result.detected).lower(),
            "reverted": str(result.reverted).lower(),
            "injected": str(result.injected).lower(),
            "stopped": str(result.stopped).lower(),
            "detection_latency_seconds": (
                "unknown"
                if result.detection_latency_seconds is None
                else str(result.detection_latency_seconds)
            ),
        },
    )


def signal_from_irp(result: IrpResult) -> ReportSignal:
    """One workload signal summarizing an IRP alert response."""
    severity = _IRP_OUTCOME_SEVERITY.get(result.outcome, Severity.MEDIUM)
    remediation = result.proposal.remediation_ref if result.proposal is not None else "-"
    return ReportSignal(
        signal_id=f"irp:{result.alert_id}",
        kind=SignalKind.IRP,
        category=ReportCategory.WORKLOAD,
        severity=severity,
        resource_ref=result.alert_id,
        title=f"IRP {result.alert_id}: {result.outcome.value}",
        detail=f"remediation={remediation}",
        occurred_at=result.ended_at,
    )


def priority_to_severity(priority: Priority) -> Severity:
    """Map an investigation priority onto a report severity."""
    return _PRIORITY_TO_SEVERITY[priority]


_SERVICE_HEALTH_LEVEL_SEVERITY: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "informational": Severity.LOW,
}

# Unknown or missing provider levels fail toward the more severe default.
_SERVICE_HEALTH_DEFAULT_SEVERITY: dict[str, Severity] = {
    "service_issue": Severity.HIGH,
    "security_advisory": Severity.HIGH,
    "health_advisory": Severity.MEDIUM,
    "planned_maintenance": Severity.LOW,
}

# A provider level never lowers a security advisory or an outage below this floor.
_SERVICE_HEALTH_SEVERITY_FLOOR: dict[str, Severity] = {
    "service_issue": Severity.MEDIUM,
    "security_advisory": Severity.MEDIUM,
}


def _service_health_severity(event_type: str, level: str | None) -> Severity:
    severity = _SERVICE_HEALTH_LEVEL_SEVERITY.get(
        (level or "").strip().casefold(), _SERVICE_HEALTH_DEFAULT_SEVERITY[event_type]
    )
    floor = _SERVICE_HEALTH_SEVERITY_FLOOR.get(event_type)
    if floor is not None and severity_rank(severity) > severity_rank(floor):
        return floor
    return severity


def signals_from_service_health(collection: ServiceHealthCollection) -> list[ReportSignal]:
    """One signal per active event and impacted resource.

    The id carries the observation day, so a still-active event is re-affirmed
    at most once per day through the idempotent store instead of every poll.
    Provider prose stays in the title only; the detail holds bounded machine fields.
    """
    day = collection.observed_at.astimezone(UTC).date().isoformat()
    signals: list[ReportSignal] = []
    if not collection.complete and not collection.observations:
        # Nothing observed and the read was incomplete: surface the gap so an empty
        # feed is never mistaken for a clear subscription.
        limitation = collection.limitation or "unknown"
        digest = hashlib.sha256(f"gap|{limitation}|{day}".encode()).hexdigest()[:32]
        signals.append(
            ReportSignal(
                signal_id=f"service-health:source_gap:{digest}",
                kind=SignalKind.SERVICE_HEALTH,
                category=ReportCategory.WORKLOAD,
                severity=Severity.MEDIUM,
                resource_ref="subscription",
                title="[Azure Service Health] source gap: active events could not be read",
                detail=f"limitation={limitation}; observed=0",
                occurred_at=collection.observed_at,
                evidence_refs=(collection.attempt_ref,),
                metadata={
                    "source": "azure-service-health",
                    "rule_id": "service-health.source_gap",
                    "collection_complete": "false",
                    "collection_limitation": limitation,
                    "execution_authority": "false",
                },
            )
        )
        return signals
    for item in collection.observations:
        identity = "|".join((item.event_evidence_ref, item.impact_evidence_ref or "", day))
        digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
        security = item.event_type == "security_advisory"
        metadata = {
            "source": "azure-service-health",
            "rule_id": f"service-health.{item.event_type}",
            "event_id": item.event_id,
            "event_type": item.event_type,
            "status": item.status,
            "impact_start_at": item.impact_start_at.isoformat(),
            "collection_complete": str(collection.complete).lower(),
            "execution_authority": "false",
        }
        for key, value in (
            ("level", item.level),
            ("resource_type", item.resource_type),
            ("resource_group", item.resource_group),
            ("region", item.region),
            ("collection_limitation", collection.limitation),
        ):
            if value is not None:
                metadata[key] = value
        count = "unknown" if item.impacted_resource_count is None else item.impacted_resource_count
        signals.append(
            ReportSignal(
                signal_id=f"service-health:{item.event_type}:{digest}",
                kind=SignalKind.SERVICE_HEALTH,
                category=ReportCategory.SECURITY if security else ReportCategory.WORKLOAD,
                severity=_service_health_severity(item.event_type, item.level),
                resource_ref=item.impacted_resource_ref or "subscription",
                title=f"[Azure Service Health] {item.event_type}: {' '.join(item.title.split())}",
                detail=(
                    f"event_type={item.event_type}; status={item.status}; "
                    f"impacted_resources={count}"
                ),
                occurred_at=collection.observed_at,
                evidence_refs=tuple(
                    ref for ref in (item.event_evidence_ref, item.impact_evidence_ref) if ref
                ),
                metadata=metadata,
            )
        )
    return signals


__all__ = [
    "priority_to_severity",
    "signal_from_experiment",
    "signal_from_irp",
    "signals_from_investigation",
    "signals_from_service_health",
]
