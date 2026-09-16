"""Reviewed ResourceType applicability and source paths for recorded state."""

from __future__ import annotations

from collections.abc import Mapping

MAX_RECORDED_STATE_VALUE_CHARS = 256
STATE_FACT_UNAVAILABLE_REASONS_PROPERTY = "state_fact_unavailable_reasons"
RECORDED_STATE_UNAVAILABLE_REASONS = frozenset(
    {
        "resource_health_not_modeled",
        "resource_health_response_invalid",
        "resource_health_response_too_large",
        "resource_health_source_unavailable",
        "resource_health_target_limit",
        "resource_health_target_unresolved",
        "resource_health_transport_unavailable",
        "resource_health_unauthorized",
        "model_serving_not_observed",
        "model_serving_response_invalid",
        "model_serving_source_unavailable",
        "model_serving_target_limit",
        "model_serving_target_unresolved",
    }
)

OPERATIONAL_STATE_PATHS = (
    "status",
    "state",
    "phase",
    "ready_status",
    "readiness",
    "runningStatus",
    "operationalState",
    "dnsResolverState",
    "diskState",
    "resourceState",
    "snapshotAccessState",
    "staticSiteEnvironmentStatus",
    "userVisibleState",
    "virtualNetworkLinkState",
    "powerState.code",
    "powerState",
    "instanceView.powerState.code",
    "extended.instanceView.powerState.code",
    "instanceView.executionState",
    "registrationStatus",
)
AVAILABILITY_STATE_PATHS = ("availabilityState",)
SERVING_STATE_PATHS = ("servingState",)

OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE: Mapping[str, tuple[str, ...]] = {
    "app-service-plan": ("powerState", "status"),
    "compute.container-app": ("runningStatus",),
    "compute.container-app-job": ("runningStatus",),
    "compute.function": ("state",),
    "compute.vm": (
        "powerState.code",
        "powerState",
        "instanceView.powerState.code",
        "extended.instanceView.powerState.code",
    ),
    "compute.vm-shutdown-schedule": ("status",),
    "compute.vm-run-command": ("instanceView.executionState",),
    "compute.web-app": ("state",),
    "disk": ("diskState",),
    "disk-snapshot": ("snapshotAccessState", "diskState"),
    "event-hub": ("status",),
    "kubernetes-cluster": ("powerState.code", "powerState"),
    "kubernetes.daemon-set": ("ready_status",),
    "kubernetes.deployment": ("ready_status",),
    "kubernetes.job": ("phase",),
    "kubernetes.node": ("ready_status",),
    "kubernetes-node-pool": ("powerState.code",),
    "kubernetes.persistent-volume": ("phase",),
    "kubernetes.persistent-volume-claim": ("phase",),
    "kubernetes.pod": ("phase",),
    "kubernetes.replica-set": ("ready_status",),
    "kubernetes.stateful-set": ("ready_status",),
    "mysql-server": ("state",),
    "network.application-gateway": ("operationalState",),
    "network.dns-resolver": ("dnsResolverState",),
    "network.private-dns-zone-link": ("virtualNetworkLinkState",),
    "network.registered-domain": ("registrationStatus",),
    "postgresql-server": ("state",),
    "redis-enterprise": ("resourceState",),
    "service-bus-namespace": ("status",),
    "search-service": ("status",),
    "sql-database": ("status",),
    "sql-server": ("state",),
    "static-web-app": ("staticSiteEnvironmentStatus",),
    "subscription": ("state",),
    "workflow.logic-app": ("state",),
}
OPERATIONAL_STATE_NOT_APPLICABLE_RESOURCE_TYPES = frozenset(
    {
        "action-group",
        "ai-project",
        "alert-rule",
        "anomaly-alert-rule",
        "application-insights",
        "authorization.role-assignment",
        "certificate",
        "devops-account",
        "compute.vm-scale-set",
        "data-collection-rule",
        "diagnostic-settings",
        "email-domain",
        "managed-certificate",
        "metric-alert-rule",
        "network.private-access-scope",
        "observability.dashboard",
        "observability.query-pack",
        "observability.solution",
        "observability.workbook",
        "prometheus-rule-group",
        "ssh-public-key",
        "kubernetes.cron-job",
        "kubernetes.endpoint-slice",
        "kubernetes.endpoints",
        "kubernetes.ingress",
        "kubernetes.ingress-class",
        "kubernetes.horizontal-pod-autoscaler",
        "kubernetes.limit-range",
        "kubernetes.namespace",
        "kubernetes.network-policy",
        "kubernetes.pod-disruption-budget",
        "kubernetes.resource-quota",
        "kubernetes.service",
        "kubernetes.storage-class",
        "log-workspace",
        "managed-identity",
        "network.private-dns-zone-group",
        "resource-group",
    }
)
PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES = frozenset(
    {
        "api-gateway",
        "bot-service",
        "cache",
        "communication-service",
        "compute.container-app-environment",
        "compute.vm-extension",
        "container-registry",
        "data-collection-endpoint",
        "email-service",
        "event-grid-topic",
        "file-share",
        "llm-endpoint",
        "llm-model-deployment",
        "managed-sre-agent",
        "metrics-workspace",
        "network.bastion-host",
        "network.dns-resolver-inbound-endpoint",
        "network.dns-zone",
        "network.firewall",
        "network.interface",
        "network.load-balancer",
        "network.nat-gateway",
        "network.nsg",
        "network.private-dns-zone",
        "network.private-endpoint",
        "network.public-ip",
        "network.route-table",
        "network.subnet",
        "network.virtual-network-gateway",
        "network.vnet",
        "nosql-database",
        "object-storage",
        "observability.dashboard-service",
        "observability.network-monitor",
        "secret-store",
        "web-search-service",
        "workflow.api-connection",
    }
)
AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE: Mapping[str, tuple[str, ...]] = {
    "alert-rule": AVAILABILITY_STATE_PATHS,
    "api-gateway": AVAILABILITY_STATE_PATHS,
    "app-service-plan": AVAILABILITY_STATE_PATHS,
    "cache": AVAILABILITY_STATE_PATHS,
    "compute.function": AVAILABILITY_STATE_PATHS,
    "compute.vm": AVAILABILITY_STATE_PATHS,
    "compute.vm-scale-set": AVAILABILITY_STATE_PATHS,
    "compute.web-app": AVAILABILITY_STATE_PATHS,
    "event-hub": AVAILABILITY_STATE_PATHS,
    "kubernetes-cluster": AVAILABILITY_STATE_PATHS,
    "llm-endpoint": AVAILABILITY_STATE_PATHS,
    "log-workspace": AVAILABILITY_STATE_PATHS,
    "metrics-workspace": AVAILABILITY_STATE_PATHS,
    "mysql-server": AVAILABILITY_STATE_PATHS,
    "network.application-gateway": AVAILABILITY_STATE_PATHS,
    "network.bastion-host": AVAILABILITY_STATE_PATHS,
    "network.dns-resolver": AVAILABILITY_STATE_PATHS,
    "network.dns-resolver-inbound-endpoint": AVAILABILITY_STATE_PATHS,
    "network.dns-zone": AVAILABILITY_STATE_PATHS,
    "network.firewall": AVAILABILITY_STATE_PATHS,
    "network.load-balancer": AVAILABILITY_STATE_PATHS,
    "network.nat-gateway": AVAILABILITY_STATE_PATHS,
    "network.virtual-network-gateway": AVAILABILITY_STATE_PATHS,
    "nosql-database": AVAILABILITY_STATE_PATHS,
    "object-storage": AVAILABILITY_STATE_PATHS,
    "observability.dashboard-service": AVAILABILITY_STATE_PATHS,
    "postgresql-server": AVAILABILITY_STATE_PATHS,
    "redis-enterprise": AVAILABILITY_STATE_PATHS,
    "secret-store": AVAILABILITY_STATE_PATHS,
    "service-bus-namespace": AVAILABILITY_STATE_PATHS,
    "search-service": AVAILABILITY_STATE_PATHS,
    "sql-database": AVAILABILITY_STATE_PATHS,
    "prometheus-rule-group": AVAILABILITY_STATE_PATHS,
}
AVAILABILITY_STATE_NOT_APPLICABLE_RESOURCE_TYPES = frozenset(
    {
        "ai-project",
        "application-insights",
        "compute.vm-run-command",
        "devops-account",
        "network.private-access-scope",
        "network.registered-domain",
        "observability.dashboard",
        "observability.query-pack",
        "observability.solution",
        "observability.workbook",
        "ssh-public-key",
    }
)
PROVIDER_AVAILABILITY_STATE_NOT_EXPOSED_RESOURCE_TYPES = frozenset(
    {
        "action-group",
        "anomaly-alert-rule",
        "authorization.role-assignment",
        "bot-service",
        "certificate",
        "communication-service",
        "compute.container-app",
        "compute.container-app-environment",
        "compute.container-app-job",
        "compute.vm-shutdown-schedule",
        "compute.vm-extension",
        "container-registry",
        "data-collection-endpoint",
        "data-collection-rule",
        "diagnostic-settings",
        "disk",
        "disk-snapshot",
        "email-domain",
        "email-service",
        "event-grid-topic",
        "file-share",
        "kubernetes-node-pool",
        "kubernetes.cron-job",
        "kubernetes.daemon-set",
        "kubernetes.deployment",
        "kubernetes.endpoint-slice",
        "kubernetes.endpoints",
        "kubernetes.horizontal-pod-autoscaler",
        "kubernetes.ingress",
        "kubernetes.ingress-class",
        "kubernetes.job",
        "kubernetes.limit-range",
        "kubernetes.namespace",
        "kubernetes.network-policy",
        "kubernetes.node",
        "kubernetes.persistent-volume",
        "kubernetes.persistent-volume-claim",
        "kubernetes.pod",
        "kubernetes.pod-disruption-budget",
        "kubernetes.replica-set",
        "kubernetes.resource-quota",
        "kubernetes.service",
        "kubernetes.stateful-set",
        "kubernetes.storage-class",
        "llm-model-deployment",
        "managed-certificate",
        "managed-sre-agent",
        "metric-alert-rule",
        "managed-identity",
        "network.interface",
        "network.nsg",
        "network.private-dns-zone",
        "network.private-dns-zone-group",
        "network.private-dns-zone-link",
        "network.private-endpoint",
        "network.public-ip",
        "network.route-table",
        "network.subnet",
        "network.vnet",
        "observability.network-monitor",
        "resource-group",
        "sql-server",
        "static-web-app",
        "subscription",
        "web-search-service",
        "workflow.api-connection",
        "workflow.logic-app",
    }
)
SERVING_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE: Mapping[str, tuple[str, ...]] = {
    "llm-model-deployment": SERVING_STATE_PATHS,
}


def operational_state_paths(resource_type: str | None) -> tuple[str, ...]:
    """Return only reviewed operational source paths for one ResourceType."""

    if resource_type is None:
        return OPERATIONAL_STATE_PATHS
    return OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE.get(resource_type, ())


def availability_state_paths(resource_type: str | None) -> tuple[str, ...]:
    """Return only reviewed availability source paths for one ResourceType."""

    if resource_type is None:
        return AVAILABILITY_STATE_PATHS
    return AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE.get(resource_type, ())


def serving_state_paths(resource_type: str | None) -> tuple[str, ...]:
    """Return only reviewed serving source paths for one ResourceType."""

    if resource_type is None:
        return SERVING_STATE_PATHS
    return SERVING_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE.get(resource_type, ())


def is_recorded_state_value_valid(value: object, *, allow_unknown: bool = False) -> bool:
    """Return whether a provider value is bounded text valid for a recorded state fact."""

    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_RECORDED_STATE_VALUE_CHARS
        and not any(ord(char) < 32 for char in value)
        and (allow_unknown or value.strip().casefold() != "unknown")
    )


__all__ = [
    "AVAILABILITY_STATE_NOT_APPLICABLE_RESOURCE_TYPES",
    "AVAILABILITY_STATE_PATHS",
    "AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE",
    "MAX_RECORDED_STATE_VALUE_CHARS",
    "OPERATIONAL_STATE_NOT_APPLICABLE_RESOURCE_TYPES",
    "OPERATIONAL_STATE_PATHS",
    "OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE",
    "PROVIDER_AVAILABILITY_STATE_NOT_EXPOSED_RESOURCE_TYPES",
    "PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES",
    "RECORDED_STATE_UNAVAILABLE_REASONS",
    "SERVING_STATE_PATHS",
    "SERVING_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE",
    "STATE_FACT_UNAVAILABLE_REASONS_PROPERTY",
    "availability_state_paths",
    "is_recorded_state_value_valid",
    "operational_state_paths",
    "serving_state_paths",
]
