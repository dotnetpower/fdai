"""Deterministic Azure inventory security assessment for AKS and MySQL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai.core.report_feed.models import ReportCategory, ReportSignal, SignalKind
from fdai.core.security import SecurityControlObservation
from fdai.delivery.azure.security_posture_aks import aks_controls
from fdai.delivery.azure.security_posture_models import (
    AzureCveEvidence,
    AzureResourceSecurityEvidence,
)
from fdai.delivery.azure.security_posture_mysql import mysql_controls
from fdai.delivery.azure.security_posture_node_pool import node_pool_controls
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.inventory import ResourceRecord


def analyze_azure_inventory_security(
    records: Sequence[ResourceRecord],
    *,
    assessed_at: datetime,
    supplemental: Mapping[str, AzureResourceSecurityEvidence] | None = None,
) -> tuple[SecurityControlObservation, ...]:
    """Evaluate supported Azure records without cloud I/O or inference."""

    evidence = supplemental or {}
    controls: list[SecurityControlObservation] = []
    for record in records:
        extra = evidence.get(record.resource_id, AzureResourceSecurityEvidence())
        if record.type == "kubernetes-cluster":
            controls.extend(aks_controls(record, extra=extra, assessed_at=assessed_at))
        elif record.type == "kubernetes-node-pool":
            controls.extend(node_pool_controls(record, assessed_at=assessed_at))
        elif record.type == "mysql-server":
            controls.extend(mysql_controls(record, extra=extra, assessed_at=assessed_at))
    return tuple(controls)


def controls_to_report_signals(
    controls: Sequence[SecurityControlObservation],
) -> tuple[ReportSignal, ...]:
    """Project normalized controls onto the existing durable report feed."""

    return tuple(
        ReportSignal(
            signal_id=(
                f"security-control:{control.control_id}:{control.resource_ref}:"
                f"{control.collected_at.isoformat()}"
            ),
            kind=SignalKind.SECURITY_ASSESSMENT,
            category=ReportCategory.SECURITY,
            severity=Severity(control.severity),
            resource_ref=control.resource_ref,
            title=control.title,
            detail=control.rationale,
            occurred_at=control.collected_at,
            evidence_refs=control.evidence_refs,
            metadata={
                "control_id": control.control_id,
                "control_category": control.category,
                "status": control.status.value,
                "resource_type": control.resource_type,
                "current_value": control.current_value,
                "expected_value": control.expected_value,
                "source": control.source,
                "remediation": control.remediation,
                "validation": control.validation,
                "priority": control.priority.value,
                "due_days": "" if control.due_days is None else str(control.due_days),
                "applicability": control.applicability,
                "cve_ids": ",".join(control.cve_ids),
                "compliance_controls": ",".join(control.compliance_controls),
                "source_urls": ",".join(control.source_urls),
                "managed_service_note": control.managed_service_note,
                "patch_status": control.patch_status,
            },
        )
        for control in controls
    )


__all__ = [
    "AzureCveEvidence",
    "AzureResourceSecurityEvidence",
    "analyze_azure_inventory_security",
    "controls_to_report_signals",
]
