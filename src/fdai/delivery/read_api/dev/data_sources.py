"""Truthful source provenance for the interactive local read API."""

from __future__ import annotations

from fdai.delivery.read_api.routes.data_sources import ReadDataSourceStatus


def build_local_data_sources(
    *,
    test_fixtures: bool,
    authoritative_proxy_configured: bool = False,
    local_database_configured: bool = False,
    local_database_startup_verified: bool = False,
    runtime_streams_configured: bool = False,
    scope_configured: bool = False,
) -> tuple[ReadDataSourceStatus, ...]:
    """Describe local composition without probing providers or inventing evidence."""

    local_state = local_database_configured and not test_fixtures
    local_state_available = local_state and local_database_startup_verified
    remote_state = authoritative_proxy_configured and not test_fixtures and not local_state
    fixture_state = ReadDataSourceStatus(
        key="operational-state",
        source=(
            "synthetic-test-fixtures"
            if test_fixtures
            else "local-postgresql"
            if local_state
            else "remote-read-api"
            if remote_state
            else "empty-local-memory"
        ),
        routes=("/audit", "/kpi", "/incidents", "/hil-queue", "/rca"),
        availability=(
            "available"
            if test_fixtures or local_state_available
            else "unknown"
            if local_state or remote_state
            else "unavailable"
        ),
        configured=True,
        reachable=True if test_fixtures or local_state_available else None,
        authoritative=local_state or remote_state,
        durable=True if local_state or remote_state else False,
        synthetic=test_fixtures,
        reason=(
            None
            if test_fixtures
            else "Reachability and freshness are verified by each local PostgreSQL request."
            if local_state
            else "Reachability and freshness are verified by each remote request."
            if remote_state
            else "Authoritative FDAI operational state is not connected to this local process."
        ),
    )
    return (
        fixture_state,
        ReadDataSourceStatus(
            key="catalogs",
            source="repository-catalogs",
            routes=(
                "/capabilities",
                "/ontology/graph",
                "/rules",
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
            key="local-metering",
            source=(
                "local-postgresql"
                if local_state
                else "remote-read-api"
                if remote_state
                else "local-process-metering"
            ),
            routes=("/kpi/llm-cost",),
            availability=(
                "available"
                if local_state_available or not (local_state or remote_state)
                else "unknown"
            ),
            configured=True,
            reachable=True if local_state_available or not (local_state or remote_state) else None,
            authoritative=True,
            durable=local_state or remote_state,
            synthetic=False,
            reason=(
                "Reachability and freshness are verified by each local PostgreSQL request."
                if local_state
                else "Reachability and freshness are verified by each remote request."
                if remote_state
                else None
            ),
        ),
        ReadDataSourceStatus(
            key="azure-inventory",
            source="azure-resource-graph",
            routes=("/inventory/graph",),
            availability="unknown",
            configured=True,
            reachable=None,
            authoritative=True,
            durable=False,
            synthetic=False,
            reason="Reachability is determined by each bounded Azure query.",
        ),
        ReadDataSourceStatus(
            key="model-catalog",
            source="azure-model-catalog",
            routes=("/models/settings",),
            availability="unknown",
            configured=True,
            reachable=None,
            authoritative=True,
            durable=False,
            synthetic=False,
            reason="Reachability is determined by each bounded Azure query.",
        ),
        ReadDataSourceStatus(
            key="onboarding",
            source="remote-read-api" if remote_state else "not-configured",
            routes=("/onboarding",),
            availability="unknown" if remote_state else "unavailable",
            configured=remote_state,
            reachable=None,
            authoritative=remote_state,
            durable=True if remote_state else None,
            synthetic=False,
            reason=(
                "Reachability and freshness are verified by each remote request."
                if remote_state
                else "No authoritative onboarding resource probe is configured."
            ),
        ),
        ReadDataSourceStatus(
            key="overview-measurement",
            source=(
                "local-postgresql"
                if local_state
                else "remote-read-api"
                if remote_state
                else "not-configured"
            ),
            routes=("/finops", "/kpi/autonomy", "/kpi/promotion-gates"),
            availability=(
                "available"
                if local_state_available
                else "unknown"
                if local_state or remote_state
                else "unavailable"
            ),
            configured=local_state or remote_state,
            reachable=True if local_state_available else None,
            authoritative=local_state or remote_state,
            durable=True if local_state or remote_state else None,
            synthetic=False,
            reason=(
                "Reachability and freshness are verified by each local PostgreSQL request."
                if local_state
                else "Reachability and freshness are verified by each remote request."
                if remote_state
                else "Durable Overview measurement providers are not configured."
            ),
        ),
        ReadDataSourceStatus(
            key="reporting",
            source=(
                "local-postgresql"
                if local_state
                else "remote-read-api"
                if remote_state
                else "not-configured"
            ),
            routes=("/reports", "/reports/registry"),
            availability=(
                "available"
                if local_state_available
                else "unknown"
                if local_state or remote_state
                else "unavailable"
            ),
            configured=local_state or remote_state,
            reachable=True if local_state_available else None,
            authoritative=local_state or remote_state,
            durable=True if local_state or remote_state else None,
            synthetic=False,
            reason=(
                "Reachability and freshness are verified by each local PostgreSQL request."
                if local_state
                else "Reachability and freshness are verified by each remote request."
                if remote_state
                else "No authoritative local reporting engine is configured."
            ),
        ),
        ReadDataSourceStatus(
            key="durable-governance",
            source=(
                "local-postgresql"
                if local_state
                else "remote-read-api"
                if remote_state
                else "not-configured"
            ),
            routes=(
                "/automation-blueprints",
                "/browser-evidence",
                "/context-selection-comparisons",
                "/conversation-delivery",
                "/operator-memory",
                "/scheduler-runs",
                "/stewardship",
            ),
            availability=(
                "available"
                if local_state_available
                else "unknown"
                if local_state or remote_state
                else "unavailable"
            ),
            configured=local_state or remote_state,
            reachable=True if local_state_available else None,
            authoritative=local_state or remote_state,
            durable=True if local_state or remote_state else None,
            synthetic=False,
            reason=(
                "Reachability and freshness are verified by each local PostgreSQL request."
                if local_state
                else "Reachability and freshness are verified by each remote request."
                if remote_state
                else "Durable governance stores are not configured."
            ),
        ),
        ReadDataSourceStatus(
            key="process-state",
            source="local-postgresql" if local_state else "interactive-local-runtime",
            routes=("/views/process", "/views/workflow-apps"),
            availability="available" if local_state_available or not local_state else "unknown",
            configured=True,
            reachable=True if local_state_available or not local_state else None,
            authoritative=True,
            durable=local_state,
            synthetic=False,
            reason=(
                "Reachability and freshness are verified by each local PostgreSQL request."
                if local_state
                else None
            ),
        ),
        ReadDataSourceStatus(
            key="local-runtime-streams",
            source="interactive-local-runtime",
            routes=("/agents/stream", "/live/stream"),
            availability="available" if runtime_streams_configured else "unavailable",
            configured=runtime_streams_configured,
            reachable=True if runtime_streams_configured else None,
            authoritative=True,
            durable=False,
            synthetic=False,
            reason=(
                None
                if runtime_streams_configured
                else "Local runtime stream relays are not configured."
            ),
        ),
        ReadDataSourceStatus(
            key="scope",
            source="deployment-environment" if scope_configured else "not-configured",
            routes=("/scope",),
            availability="unknown" if scope_configured else "unavailable",
            configured=scope_configured,
            reachable=None,
            authoritative=scope_configured,
            durable=True if scope_configured else None,
            synthetic=False,
            reason=(
                "Scope is derived from the deployment environment."
                if scope_configured
                else "Deployment scope environment is not configured."
            ),
        ),
        ReadDataSourceStatus(
            key="identity",
            source="microsoft-entra",
            routes=("/iam", "/iam/self"),
            availability="unknown",
            configured=True,
            reachable=None,
            authoritative=True,
            durable=None,
            synthetic=False,
            reason="Directory reachability is verified by each Microsoft Graph request.",
        ),
    )


__all__ = ["build_local_data_sources"]
