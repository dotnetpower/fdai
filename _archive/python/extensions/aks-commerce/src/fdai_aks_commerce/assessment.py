"""Deterministic AKS commerce business-impact assessment."""

from __future__ import annotations

import hashlib
import json

from fdai_service_contracts import (
    AksCommerceProjection,
    AksCommerceStatus,
)

from fdai_aks_commerce.models import (
    AksCommerceAssessmentPolicy,
    AksCommerceEvidenceFrame,
)

_DEGRADED = frozenset(
    {
        AksCommerceStatus.CATALOG_UNAVAILABLE,
        AksCommerceStatus.DEAD_LETTER_GROWTH,
        AksCommerceStatus.DEPENDENCY_PRESSURE,
        AksCommerceStatus.DEPLOYMENT_REGRESSION,
        AksCommerceStatus.ORDER_BACKLOG,
    }
)


def assess_aks_commerce(
    frame: AksCommerceEvidenceFrame,
    *,
    policy: AksCommerceAssessmentPolicy | None = None,
) -> AksCommerceProjection:
    """Reduce one qualified evidence frame without granting execution authority."""

    selected = policy or AksCommerceAssessmentPolicy()
    gaps = list(frame.derived_gaps)
    required = selected.required_metrics.get(frame.service_id, ())
    for metric_name in required:
        metric = frame.metric(metric_name)
        if metric is None:
            gaps.append(f"metric_missing.{metric_name}")
    gaps = list(dict.fromkeys(gaps))
    if gaps:
        status = AksCommerceStatus.HELD
    else:
        status = _qualified_status(frame, selected)
        if status is AksCommerceStatus.HELD:
            gaps.append("health_not_proven")
    affected = (
        tuple(workload.workload_id for workload in frame.workloads if workload.ready is False)
        if status is not AksCommerceStatus.HEALTHY
        else ()
    )
    summary = _summary(frame.service_id, status)
    payload = {
        "service_id": frame.service_id,
        "status": status.value,
        "observed_at": frame.observed_at.isoformat(),
        "window_start": frame.window_start.isoformat(),
        "window_end": frame.window_end.isoformat(),
        "dependency_path": frame.dependency_path,
        "evidence_refs": frame.evidence_refs,
        "evidence_gaps": gaps,
    }
    identity = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return AksCommerceProjection(
        assessment_id=f"sha256:{identity}",
        service_id=frame.service_id,
        status=status,
        summary=summary,
        observed_at=frame.observed_at,
        window_start=frame.window_start,
        window_end=frame.window_end,
        complete=not gaps,
        synthetic=frame.synthetic,
        affected_workload_ids=affected,
        dependency_path=frame.dependency_path,
        workloads=frame.workloads,
        metrics=frame.metrics,
        slos=frame.slos,
        evidence_gaps=tuple(gaps),
        evidence_refs=frame.evidence_refs,
    )


def _qualified_status(
    frame: AksCommerceEvidenceFrame,
    policy: AksCommerceAssessmentPolicy,
) -> AksCommerceStatus:
    any_slo_breached = any(slo.breached is True for slo in frame.slos)
    catalog = frame.metric(policy.catalog_availability_metric)
    if (
        frame.service_id == "catalog-browse"
        and catalog is not None
        and catalog.current == 0
        and any(workload.ready is False for workload in frame.workloads)
    ):
        return AksCommerceStatus.CATALOG_UNAVAILABLE

    dead_letters = frame.metric(policy.dead_letter_messages_metric)
    if _growth(dead_letters) >= policy.dead_letter_growth_minimum:
        return AksCommerceStatus.DEAD_LETTER_GROWTH

    active = frame.metric(policy.active_messages_metric)
    incoming = frame.metric(policy.incoming_messages_metric)
    completed = frame.metric(policy.completed_messages_metric)
    backlog_growth = _growth(active)
    if (
        backlog_growth >= policy.backlog_growth_minimum
        and incoming is not None
        and completed is not None
        and incoming.current is not None
        and completed.current is not None
        and incoming.current > completed.current
    ):
        if frame.deployment_changed and frame.rollout_stalled and any_slo_breached:
            return AksCommerceStatus.DEPLOYMENT_REGRESSION
        return AksCommerceStatus.ORDER_BACKLOG

    if any_slo_breached and frame.order_store_pressure:
        return AksCommerceStatus.DEPENDENCY_PRESSURE
    if frame.deployment_changed and frame.rollout_stalled and any_slo_breached:
        return AksCommerceStatus.DEPLOYMENT_REGRESSION
    availability = (
        catalog
        if frame.service_id == "catalog-browse"
        else frame.metric("synthetic.order.availability")
    )
    if (
        availability is None
        or availability.current != 1
        or any(slo.breached is not False for slo in frame.slos)
        or any(workload.ready is not True for workload in frame.workloads)
    ):
        return AksCommerceStatus.HELD
    if frame.prior_degraded:
        return AksCommerceStatus.RECOVERED
    return AksCommerceStatus.HEALTHY


def _growth(metric: object) -> float:
    current = getattr(metric, "current", None)
    previous = getattr(metric, "previous", None)
    if not isinstance(current, int | float) or not isinstance(previous, int | float):
        return 0.0
    return float(current) - float(previous)


def _summary(service_id: str, status: AksCommerceStatus) -> str:
    service = "Order fulfillment" if service_id == "order-fulfillment" else "Catalog browse"
    messages = {
        AksCommerceStatus.CATALOG_UNAVAILABLE: f"{service} is unavailable.",
        AksCommerceStatus.DEAD_LETTER_GROWTH: f"{service} has growing dead-letter volume.",
        AksCommerceStatus.DEPENDENCY_PRESSURE: f"{service} is degraded by dependency pressure.",
        AksCommerceStatus.DEPLOYMENT_REGRESSION: f"{service} regressed after a workload revision.",
        AksCommerceStatus.HEALTHY: f"{service} is healthy for the assessed window.",
        AksCommerceStatus.HELD: f"{service} is held because required evidence is incomplete.",
        AksCommerceStatus.ORDER_BACKLOG: f"{service} has a growing order backlog.",
        AksCommerceStatus.RECOVERED: f"{service} recovered in the assessed window.",
    }
    return messages[status]
