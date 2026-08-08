"""Pure converters - module outputs -> normalized report signals.

Turns the outputs of the investigation, chaos, and IRP modules into
:class:`ReportSignal` values for the report feed. Deterministic and
I/O-free so "this outcome produces these signals" is exhaustively testable.
"""

from __future__ import annotations

from fdai.core.chaos.contract import ExperimentOutcome, ExperimentResult
from fdai.core.investigation.contract import InvestigationReport, Priority
from fdai.core.irp.coordinator import IrpOutcome, IrpResult
from fdai.core.report_feed.models import (
    ReportCategory,
    ReportSignal,
    SignalKind,
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


__all__ = [
    "priority_to_severity",
    "signal_from_experiment",
    "signal_from_irp",
    "signals_from_investigation",
]
