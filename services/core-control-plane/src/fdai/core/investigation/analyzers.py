"""Reference resource analyzers for the demo's five resource kinds.

Each builder returns a :class:`ThresholdAnalyzer` pre-loaded with the
signals the Azure SRE Agent demo (session notes slides 11-12) analyzes:

- Application Gateway - backend first-byte latency, healthy host count.
- Azure Database for MySQL - CPU %, connection count.
- Azure OpenAI - HTTP 429 rate-limit rate, request volume surge.
- AKS - node/pod CPU %.
- API Management - backend latency, 5xx rate.

Thresholds are **configuration-shaped defaults**, kept CSP-neutral and
customer-agnostic; a fork tunes them per environment by registering its
own analyzers. Nothing here executes a change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType

from fdai.core.investigation.analyzer import (
    Aggregation,
    Comparison,
    ResourceAnalyzer,
    Threshold,
    ThresholdAnalyzer,
)
from fdai.core.investigation.kubernetes_pod import (
    KIND_KUBERNETES_POD,
    KubernetesPodLifecycleAnalyzer,
    PodLifecycleEvidenceSource,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import MetricProvider

_Clock = Callable[[], datetime] | None

# Canonical resource-kind identifiers (CSP-neutral vocabulary handles).
KIND_APP_GATEWAY = "application_gateway"
KIND_MYSQL = "mysql_flexible_server"
KIND_POSTGRESQL = "postgresql_flexible_server"
KIND_REDIS = "redis_cache"
KIND_KEY_VAULT = "key_vault"
KIND_COSMOS_DB = "cosmos_db"
KIND_SERVICE_BUS = "service_bus"
KIND_AZURE_OPENAI = "azure_openai"
KIND_AKS = "aks_cluster"
KIND_API_MANAGEMENT = "api_management"


def app_gateway_analyzer(
    provider: MetricProvider, *, wall_clock: _Clock = None
) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_APP_GATEWAY,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="backend_first_byte_response_time_ms",
                compare=Comparison.GTE,
                bound=2_000.0,
                severity=Severity.HIGH,
                signal="backend_latency",
                observation="Backend first-byte response time is elevated.",
                remediation_ref="appgw.add_backend_health_probe",
            ),
            Threshold(
                metric="healthy_host_count",
                compare=Comparison.LTE,
                bound=1.0,
                severity=Severity.CRITICAL,
                signal="backend_health",
                observation="Healthy backend host count collapsed (pool near empty).",
                aggregation=Aggregation.MIN,
                remediation_ref="appgw.scale_backend_pool",
            ),
        ),
    )


def mysql_analyzer(provider: MetricProvider, *, wall_clock: _Clock = None) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_MYSQL,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="cpu_percent",
                compare=Comparison.GTE,
                bound=90.0,
                severity=Severity.HIGH,
                signal="db_cpu",
                observation="MySQL CPU is saturated; slow queries likely.",
                remediation_ref="mysql.investigate_slow_queries",
            ),
            Threshold(
                metric="active_connections",
                compare=Comparison.GTE,
                bound=100.0,
                severity=Severity.MEDIUM,
                signal="db_connections",
                observation="MySQL active connection count surged.",
            ),
        ),
    )


def azure_openai_analyzer(
    provider: MetricProvider, *, wall_clock: _Clock = None
) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_AZURE_OPENAI,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="http_429_rate",
                compare=Comparison.GTE,
                bound=0.05,
                severity=Severity.HIGH,
                signal="rate_limit",
                observation="Azure OpenAI is returning HTTP 429 rate-limit errors.",
                remediation_ref="aoai.increase_tpm_quota",
            ),
            Threshold(
                metric="request_surge_ratio",
                compare=Comparison.GTE,
                bound=10.0,
                severity=Severity.MEDIUM,
                signal="request_surge",
                observation="Azure OpenAI request volume surged well above baseline.",
            ),
        ),
    )


def aks_analyzer(provider: MetricProvider, *, wall_clock: _Clock = None) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_AKS,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="node_cpu_percent",
                compare=Comparison.GTE,
                bound=80.0,
                severity=Severity.MEDIUM,
                signal="node_cpu",
                observation="AKS node CPU is high; autoscaling may be in progress.",
            ),
            Threshold(
                metric="pod_restart_count",
                compare=Comparison.GTE,
                bound=1.0,
                severity=Severity.HIGH,
                signal="pod_restart",
                observation="One or more Kubernetes pods restarted in the observation window.",
                remediation_ref="ops.restart-service",
            ),
            Threshold(
                metric="rollout_stall_duration_seconds",
                compare=Comparison.GTE,
                bound=120.0,
                severity=Severity.HIGH,
                signal="rollout_stall",
                observation="A Kubernetes deployment rollout remained stalled past the bound.",
            ),
        ),
    )


def api_management_analyzer(
    provider: MetricProvider, *, wall_clock: _Clock = None
) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_API_MANAGEMENT,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="http_5xx_rate",
                compare=Comparison.GTE,
                bound=0.05,
                severity=Severity.HIGH,
                signal="gateway_5xx",
                observation="API Management 5xx error rate is elevated.",
            ),
            Threshold(
                metric="backend_latency_ms",
                compare=Comparison.GTE,
                bound=1_000.0,
                severity=Severity.MEDIUM,
                signal="gateway_latency",
                observation="API Management backend latency is elevated.",
            ),
        ),
    )


def postgresql_analyzer(
    provider: MetricProvider, *, wall_clock: _Clock = None
) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_POSTGRESQL,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="postgresql_cpu_percent",
                compare=Comparison.GTE,
                bound=90.0,
                severity=Severity.HIGH,
                signal="postgresql_cpu",
                observation="PostgreSQL CPU utilization is saturated.",
            ),
            Threshold(
                metric="postgresql_storage_percent",
                compare=Comparison.GTE,
                bound=85.0,
                severity=Severity.HIGH,
                signal="postgresql_storage",
                observation="PostgreSQL storage utilization is approaching capacity.",
            ),
            Threshold(
                metric="postgresql_connections_failed",
                compare=Comparison.GTE,
                bound=1.0,
                severity=Severity.HIGH,
                signal="postgresql_connections_failed",
                observation="PostgreSQL failed connection attempts detected.",
            ),
        ),
    )


def redis_analyzer(provider: MetricProvider, *, wall_clock: _Clock = None) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_REDIS,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="redis_server_load",
                compare=Comparison.GTE,
                bound=85.0,
                severity=Severity.HIGH,
                signal="redis_load",
                observation="Redis server load is saturated.",
            ),
            Threshold(
                metric="redis_used_memory_percentage",
                compare=Comparison.GTE,
                bound=90.0,
                severity=Severity.HIGH,
                signal="redis_memory",
                observation="Redis memory utilization is critically high.",
            ),
        ),
    )


def key_vault_analyzer(provider: MetricProvider, *, wall_clock: _Clock = None) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_KEY_VAULT,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="key_vault_saturation_shoebox",
                compare=Comparison.GTE,
                bound=85.0,
                severity=Severity.HIGH,
                signal="key_vault_saturation",
                observation="Key Vault throttling saturation is elevated.",
            ),
            Threshold(
                metric="key_vault_availability",
                compare=Comparison.LTE,
                bound=99.0,
                severity=Severity.CRITICAL,
                signal="key_vault_availability",
                observation="Key Vault availability dropped below 99%.",
                aggregation=Aggregation.MIN,
            ),
        ),
    )


def cosmos_db_analyzer(provider: MetricProvider, *, wall_clock: _Clock = None) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_COSMOS_DB,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="cosmos_normalized_ru_consumption_percent",
                compare=Comparison.GTE,
                bound=90.0,
                severity=Severity.HIGH,
                signal="cosmos_ru_saturation",
                observation="Cosmos DB normalized RU consumption is saturated.",
            ),
            Threshold(
                metric="cosmos_http_429_rate",
                compare=Comparison.GTE,
                bound=0.05,
                severity=Severity.HIGH,
                signal="cosmos_rate_limit",
                observation="Cosmos DB is returning HTTP 429 request-rate-too-large errors.",
            ),
        ),
    )


def service_bus_analyzer(
    provider: MetricProvider, *, wall_clock: _Clock = None
) -> ThresholdAnalyzer:
    return ThresholdAnalyzer(
        resource_kind=KIND_SERVICE_BUS,
        provider=provider,
        wall_clock=wall_clock,
        thresholds=(
            Threshold(
                metric="service_bus_dead_lettered_messages",
                compare=Comparison.GTE,
                bound=1.0,
                severity=Severity.HIGH,
                signal="service_bus_dead_letter",
                observation="Service Bus dead-lettered messages detected in the window.",
            ),
            Threshold(
                metric="service_bus_throttled_requests",
                compare=Comparison.GTE,
                bound=5.0,
                severity=Severity.MEDIUM,
                signal="service_bus_throttled",
                observation="Service Bus throttled requests exceeded threshold.",
            ),
        ),
    )


#: Reviewed map from the neutral ``rule-catalog/vocabulary/resource-types.yaml``
#: id an inventory projection records on ``Resource.type`` to the analyzer kind
#: that observes it. An inventory
#: resource type absent from this map has no analyzer and is never guessed at.
ANALYZER_KIND_BY_RESOURCE_TYPE: Mapping[str, str] = MappingProxyType(
    {
        "api-gateway": KIND_API_MANAGEMENT,
        "kubernetes-cluster": KIND_AKS,
        "kubernetes.pod": KIND_KUBERNETES_POD,
        "llm-endpoint": KIND_AZURE_OPENAI,
        "mysql-server": KIND_MYSQL,
        "network.application-gateway": KIND_APP_GATEWAY,
        "compute.vm": "virtual_machine",
        "compute.vm-scale-set": "virtual_machine_scale_set",
    }
)


def default_analyzers(
    provider: MetricProvider,
    *,
    wall_clock: _Clock = None,
    pod_lifecycle_evidence: PodLifecycleEvidenceSource | None = None,
) -> tuple[ResourceAnalyzer, ...]:
    """The reference analyzers wired to one shared metric provider.

    The typed Kubernetes Pod lifecycle analyzer joins the set only when a
    deployment bound an evidence source for it. An unbound source leaves Pod
    targets unsupported rather than analyzed on absent observations, so a
    receipt never reports a lifecycle conclusion nobody observed.
    """
    from fdai.core.investigation.host_cpu import HostCpuAnalyzer

    return (
        app_gateway_analyzer(provider, wall_clock=wall_clock),
        mysql_analyzer(provider, wall_clock=wall_clock),
        azure_openai_analyzer(provider, wall_clock=wall_clock),
        aks_analyzer(provider, wall_clock=wall_clock),
        api_management_analyzer(provider, wall_clock=wall_clock),
        HostCpuAnalyzer(provider, wall_clock=wall_clock),
        HostCpuAnalyzer(provider, resource_kind="virtual_machine_scale_set", wall_clock=wall_clock),
        *(
            (KubernetesPodLifecycleAnalyzer(pod_lifecycle_evidence),)
            if pod_lifecycle_evidence is not None
            else ()
        ),
    )


__all__ = [
    "ANALYZER_KIND_BY_RESOURCE_TYPE",
    "KIND_AKS",
    "KIND_KUBERNETES_POD",
    "KIND_API_MANAGEMENT",
    "KIND_APP_GATEWAY",
    "KIND_AZURE_OPENAI",
    "KIND_COSMOS_DB",
    "KIND_KEY_VAULT",
    "KIND_MYSQL",
    "KIND_POSTGRESQL",
    "KIND_REDIS",
    "KIND_SERVICE_BUS",
    "aks_analyzer",
    "api_management_analyzer",
    "app_gateway_analyzer",
    "azure_openai_analyzer",
    "cosmos_db_analyzer",
    "default_analyzers",
    "key_vault_analyzer",
    "mysql_analyzer",
    "postgresql_analyzer",
    "redis_analyzer",
    "service_bus_analyzer",
]
