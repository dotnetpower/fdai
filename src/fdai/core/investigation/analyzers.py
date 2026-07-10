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

from collections.abc import Callable
from datetime import datetime

from fdai.core.investigation.analyzer import (
    Aggregation,
    Comparison,
    ResourceAnalyzer,
    Threshold,
    ThresholdAnalyzer,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import MetricProvider

_Clock = Callable[[], datetime] | None

# Canonical resource-kind identifiers (CSP-neutral vocabulary handles).
KIND_APP_GATEWAY = "application_gateway"
KIND_MYSQL = "mysql_flexible_server"
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


def default_analyzers(
    provider: MetricProvider, *, wall_clock: _Clock = None
) -> tuple[ResourceAnalyzer, ...]:
    """The five reference analyzers wired to one shared metric provider."""
    return (
        app_gateway_analyzer(provider, wall_clock=wall_clock),
        mysql_analyzer(provider, wall_clock=wall_clock),
        azure_openai_analyzer(provider, wall_clock=wall_clock),
        aks_analyzer(provider, wall_clock=wall_clock),
        api_management_analyzer(provider, wall_clock=wall_clock),
    )


__all__ = [
    "KIND_AKS",
    "KIND_API_MANAGEMENT",
    "KIND_APP_GATEWAY",
    "KIND_AZURE_OPENAI",
    "KIND_MYSQL",
    "aks_analyzer",
    "api_management_analyzer",
    "app_gateway_analyzer",
    "azure_openai_analyzer",
    "default_analyzers",
    "mysql_analyzer",
]
