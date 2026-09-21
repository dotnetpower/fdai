"""Truthful read data-source metadata for the independent Operator service."""

from __future__ import annotations

from fdai_service_contracts import ReadDataSource


def _build_data_sources(
    *, configured: bool, inventory_configured: bool
) -> tuple[ReadDataSource, ...]:
    reason = None if configured else "Authoritative service-local projections are not configured."
    return (
        ReadDataSource(
            key="observer-deployment-proposals",
            source="operator-observer-proposal-projection"
            if inventory_configured
            else "not-configured",
            routes=("/observer-deployment-proposals",),
            availability="unknown" if inventory_configured else "unavailable",
            configured=inventory_configured,
            reachable=None,
            authoritative=inventory_configured,
            durable=True if inventory_configured else None,
            reason=None
            if inventory_configured
            else "Observer proposal projection is not configured.",
        ),
        ReadDataSource(
            key="alert-quality",
            source="operator-alert-quality-projection"
            if inventory_configured
            else "not-configured",
            routes=("/alert-quality",),
            availability="unknown" if inventory_configured else "unavailable",
            configured=inventory_configured,
            reachable=None,
            authoritative=inventory_configured,
            durable=True if inventory_configured else None,
            reason=(
                None
                if inventory_configured
                else "Authoritative alert quality projections are not configured."
            ),
        ),
        ReadDataSource(
            key="ontology-instances",
            source="service-local-inventory" if inventory_configured else "not-configured",
            routes=(
                "/ontology/instances",
                "/ontology/instances/explore",
                "/ontology/instances/states",
            ),
            availability="unknown" if inventory_configured else "unavailable",
            configured=inventory_configured,
            reachable=None,
            authoritative=inventory_configured,
            durable=True if inventory_configured else None,
            reason=(
                None
                if inventory_configured
                else "Authoritative inventory instance projections are not configured."
            ),
        ),
        ReadDataSource(
            key="operational-state",
            source="service-local-projection" if configured else "not-configured",
            routes=(
                "/audit",
                "/audit/{correlation_id}/trace",
                "/browser-evidence",
                "/hil-queue",
                "/incidents",
                "/incidents/stream",
                "/kpi",
                "/kpi/llm-cost",
                "/rca",
                "/assurance-twin/posture",
                "/assurance-twin/reviews",
                "/assurance-twin/review",
            ),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="aks-commerce",
            source="core-tracked-state" if configured else "not-configured",
            routes=("/aks-commerce/overview",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="cost-governance",
            source="retained-cost-observation" if configured else "not-configured",
            routes=(
                "/cost-governance/availability",
                "/cost-governance/settings",
                "/cost-governance/overview",
                "/cost-governance/resource-efficiency",
                "/cost-governance/optimization-cases",
                "/cost-governance/outcomes",
                "/finops",
            ),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="overview-measurement",
            source="not-served-by-operator-service",
            routes=("/overview/measurement",),
            availability="unavailable",
            configured=False,
            reachable=False,
            authoritative=False,
            durable=None,
            reason="Overview measurement is owned by a separate projection service.",
        ),
        ReadDataSource(
            key="autonomy-measurement",
            source="outcome-assurance-measurement" if configured else "not-configured",
            routes=("/kpi/autonomy",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="promotion-gate-evidence",
            source=(
                "catalog-and-promotion-registry-projection" if configured else "not-configured"
            ),
            routes=("/kpi/promotion-gates",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="onboarding-probe",
            source="repository-catalog-projection" if configured else "not-configured",
            routes=("/onboarding",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="detection-readiness",
            source="service-local-projection" if configured else "not-configured",
            routes=("/detection-coverage", "/detection-readiness"),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="workflow-app-catalog",
            source="repository-catalog-projection" if configured else "not-configured",
            routes=("/views/workflow-apps",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="configuration-baseline",
            source="service-local-projection" if configured else "not-configured",
            routes=("/configuration-baselines",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="conversation-delivery",
            source="operator-delivery-ledger" if configured else "not-configured",
            routes=("/conversation-delivery",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="capability-contract",
            source="repository-catalog-projection" if configured else "not-configured",
            routes=("/capabilities",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="runtime-skill",
            source="service-local-projection" if configured else "not-configured",
            routes=("/skills",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="forecast-learning",
            source="service-local-projection" if configured else "not-configured",
            routes=("/forecast-learning",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="operator-memory",
            source="service-local-projection" if configured else "not-configured",
            routes=("/operator-memory",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="notification-template",
            source="operator-service",
            routes=("/notification-templates/incident-opened",),
            availability="available",
            configured=True,
            reachable=True,
            authoritative=True,
            durable=False,
        ),
    )


__all__ = ["_build_data_sources"]
