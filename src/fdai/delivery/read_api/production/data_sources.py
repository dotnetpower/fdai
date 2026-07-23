"""Composition-owned source provenance for the production read API."""

from __future__ import annotations

from fdai.delivery.read_api.routes.data_sources import ReadDataSourceStatus


def build_production_data_sources(
    *,
    scope_configured: bool,
    onboarding_configured: bool,
    model_settings_configured: bool,
    streams_configured: bool,
) -> tuple[ReadDataSourceStatus, ...]:
    """Describe production providers without inferring request-time reachability."""

    return (
        _unknown(
            "operational-state",
            "postgres",
            ("/audit", "/kpi", "/incidents", "/hil-queue", "/rca"),
            durable=True,
        ),
        _unknown(
            "overview-measurement",
            "postgres-audit-and-promotion-state",
            ("/finops", "/kpi/autonomy", "/kpi/promotion-gates"),
            durable=True,
        ),
        _configured(
            "scope",
            "deployment-environment" if scope_configured else "not-configured",
            ("/scope",),
            configured=scope_configured,
            durable=True if scope_configured else None,
            reason="Deployment scope environment is not configured.",
        ),
        _unknown(
            "reporting",
            "postgres-reporting",
            ("/reports", "/reports/registry"),
            durable=True,
        ),
        _unknown(
            "inventory",
            "postgres-inventory-snapshot",
            ("/inventory/graph",),
            durable=True,
        ),
        _unknown(
            "metering",
            "postgres-metering",
            ("/kpi/llm-cost",),
            durable=True,
        ),
        _unknown(
            "durable-governance",
            "postgres",
            (
                "/automation-blueprints",
                "/browser-evidence",
                "/context-selection-comparisons",
                "/conversation-delivery",
                "/forecast-learning",
                "/me/context",
                "/me/conversations/search",
                "/operator-memory",
                "/scheduler-runs",
                "/workflows/definitions",
            ),
            durable=True,
        ),
        _unknown(
            "python-tasks",
            "postgres-and-event-bus",
            ("/python-tasks",),
            durable=True,
        ),
        _unknown(
            "runtime-skills",
            "postgres-trusted-artifacts",
            ("/skills",),
            durable=True,
        ),
        _configured(
            "onboarding",
            "azure-resource-probe" if onboarding_configured else "not-configured",
            ("/onboarding",),
            configured=onboarding_configured,
            durable=False if onboarding_configured else None,
            reason="Azure onboarding probe configuration is incomplete.",
        ),
        _configured(
            "models",
            "resolved-models" if model_settings_configured else "not-configured",
            ("/models/settings",),
            configured=model_settings_configured,
            durable=True if model_settings_configured else None,
            reason="Resolved model settings are not configured.",
        ),
        _configured(
            "streams",
            "event-hubs-kafka" if streams_configured else "not-configured",
            ("/live/stream", "/agents/stream"),
            configured=streams_configured,
            durable=False if streams_configured else None,
            reason="Kafka stage streams are not configured.",
        ),
        ReadDataSourceStatus(
            key="catalogs",
            source="repository-catalogs",
            routes=(
                "/capabilities",
                "/ontology/graph",
                "/rules",
                "/workflows/action-types",
                "/workflows/catalog",
            ),
            availability="available",
            configured=True,
            reachable=True,
            authoritative=True,
            durable=True,
            synthetic=False,
        ),
        ReadDataSourceStatus(
            key="stewardship-config",
            source="repository-config",
            routes=("/stewardship",),
            availability="available",
            configured=True,
            reachable=True,
            authoritative=True,
            durable=True,
            synthetic=False,
        ),
        ReadDataSourceStatus(
            key="provisioning-stream",
            source="not-configured",
            routes=("/provision/stream",),
            availability="unavailable",
            configured=False,
            reachable=None,
            authoritative=False,
            durable=None,
            synthetic=False,
            reason="No authoritative provisioning stream relay is configured.",
        ),
        _unknown("identity", "microsoft-entra", ("/iam", "/iam/self"), durable=None),
    )


def _unknown(
    key: str,
    source: str,
    routes: tuple[str, ...],
    *,
    durable: bool | None,
) -> ReadDataSourceStatus:
    return ReadDataSourceStatus(
        key=key,
        source=source,
        routes=routes,
        availability="unknown",
        configured=True,
        reachable=None,
        authoritative=True,
        durable=durable,
        synthetic=False,
        reason="Reachability and freshness are verified by each request.",
    )


def _configured(
    key: str,
    source: str,
    routes: tuple[str, ...],
    *,
    configured: bool,
    durable: bool | None,
    reason: str,
) -> ReadDataSourceStatus:
    if configured:
        return _unknown(key, source, routes, durable=durable)
    return ReadDataSourceStatus(
        key=key,
        source=source,
        routes=routes,
        availability="unavailable",
        configured=False,
        reachable=None,
        authoritative=False,
        durable=durable,
        synthetic=False,
        reason=reason,
    )


__all__ = ["build_production_data_sources"]
