"""Run one bounded workload SLO burn evaluation from a scheduled job."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from fdai.composition import attach_metric_provider, default_container_from_env
from fdai.core.slo import MetricBurnRateSource, SloBurnRunner, SloBurnRunReport, SloRegistry
from fdai.delivery.azure.demo_queries import default_metric_queries
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.runtime.venue import (
    ExecutionVenue,
    bus_security_protocol,
    resolve_execution_venue,
    uses_developer_identity,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.metric import MetricProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.slo_burn")

CATALOG_DIR_ENV = "FDAI_SLO_CATALOG_DIR"
BOOTSTRAP_SERVERS_ENV = "KAFKA_BOOTSTRAP_SERVERS"
TOPIC_ENV = "FDAI_SLO_BURN_TOPIC"
INGRESS_TOPIC_ENV = "KAFKA_TOPIC_EVENTS"
TIMEOUT_ENV = "FDAI_SLO_BURN_TIMEOUT_SECONDS"
_DEFAULT_TIMEOUT_SECONDS = 240


class SloBurnJobConfigurationError(ValueError):
    """Required SLO job bindings are missing or outside their bounds."""


@dataclass(frozen=True, slots=True)
class SloBurnJobSettings:
    """Validated bindings for one workload SLO evaluation fire."""

    catalog_dir: Path
    bootstrap_servers: str
    topic: str
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.bootstrap_servers.strip() or not self.topic.strip():
            raise SloBurnJobConfigurationError("SLO burn bus bindings MUST be non-empty")
        if not 1 <= self.timeout_seconds <= 300:
            raise SloBurnJobConfigurationError("SLO burn timeout_seconds MUST be between 1 and 300")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> SloBurnJobSettings:
        """Load public bindings without retaining or rendering secret values."""

        catalog = _required(environ, CATALOG_DIR_ENV)
        topic = environ.get(TOPIC_ENV, "").strip() or environ.get(INGRESS_TOPIC_ENV, "").strip()
        if not topic:
            raise SloBurnJobConfigurationError(f"{TOPIC_ENV} or {INGRESS_TOPIC_ENV} is required")
        return cls(
            catalog_dir=Path(catalog),
            bootstrap_servers=_required(environ, BOOTSTRAP_SERVERS_ENV),
            topic=topic,
            timeout_seconds=_bounded_integer(
                environ.get(TIMEOUT_ENV, ""),
                name=TIMEOUT_ENV,
                default=_DEFAULT_TIMEOUT_SECONDS,
                minimum=1,
                maximum=300,
            ),
        )


async def execute_slo_burn(
    *,
    settings: SloBurnJobSettings,
    registry: SloRegistry,
    metric_provider: MetricProvider,
    event_bus: EventBus,
    now: datetime | None = None,
) -> SloBurnRunReport:
    """Evaluate a non-empty registry once under one total deadline."""

    if not registry.all():
        raise SloBurnJobConfigurationError("SLO burn catalog MUST contain at least one objective")
    async with asyncio.timeout(settings.timeout_seconds):
        return await SloBurnRunner(
            registry=registry,
            source=MetricBurnRateSource(metric_provider),
            event_bus=event_bus,
            topic=settings.topic,
        ).run_once(now=now)


async def run_once(environ: Mapping[str, str] | None = None) -> SloBurnRunReport:
    """Compose real metric and Kafka adapters for one scheduled invocation."""

    environment = os.environ if environ is None else environ
    settings = SloBurnJobSettings.from_environ(environment)
    registry = SloRegistry.from_directory(settings.catalog_dir)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    ) as http_client:
        venue = resolve_execution_venue(environment)
        identity = _build_identity(http_client, venue=venue)
        container = attach_metric_provider(
            default_container_from_env(environment),
            identity=identity,
            http_client=http_client,
            monitor_workspace_id=_optional(environment, "FDAI_MONITOR_WORKSPACE_ID"),
            monitor_queries=default_metric_queries(),
            metrics_api_queries=None,
            prometheus_base_url=_optional(environment, "FDAI_PROMETHEUS_ENDPOINT"),
            prometheus_queries=None,
            prometheus_audience=_optional(environment, "FDAI_PROMETHEUS_AUDIENCE"),
        )
        bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=settings.bootstrap_servers,
                security_protocol=bus_security_protocol(venue),
                client_id="fdai-slo-burn-job",
            ),
        )
        try:
            return await execute_slo_burn(
                settings=settings,
                registry=registry,
                metric_provider=container.metric_provider,
                event_bus=bus,
            )
        finally:
            await bus.close()


def report_summary(report: SloBurnRunReport) -> dict[str, object]:
    """Return a bounded status that never treats missing telemetry as healthy."""

    incomplete = report.insufficient > 0 or bool(report.evaluation_errors)
    failed = incomplete or bool(report.publish_errors)
    return {
        "status": "retry_required" if failed else "completed",
        "evaluated": report.evaluated,
        "breached": report.breached,
        "published": report.published,
        "insufficient": report.insufficient,
        "evaluation_error_count": len(report.evaluation_errors),
        "publish_error_count": len(report.publish_errors),
        "execution_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Run one pass and return stable configuration, retry, or success status."""

    arguments = argv if argv is not None else sys.argv[1:]
    if arguments:
        print(json.dumps({"status": "invalid_arguments"}, sort_keys=True))
        return 2
    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    try:
        report = asyncio.run(run_once())
    except SloBurnJobConfigurationError as exc:
        _LOGGER.error("slo_burn_configuration_invalid", extra={"error_kind": type(exc).__name__})
        print(json.dumps({"status": "configuration_required"}, sort_keys=True))
        return 2
    except (TimeoutError, OSError) as exc:
        _LOGGER.error("slo_burn_failed", extra={"error_kind": type(exc).__name__})
        print(
            json.dumps(
                {"status": "retry_required", "error_kind": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1

    summary = report_summary(report)
    _LOGGER.info("slo_burn_complete", extra=summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "completed" else 1


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SloBurnJobConfigurationError(f"{name} is required")
    return value


def _bounded_integer(
    raw: str,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SloBurnJobConfigurationError(f"{name} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise SloBurnJobConfigurationError(f"{name} MUST be between {minimum} and {maximum}")
    return value


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    return environ.get(name, "").strip() or None


def _build_identity(
    http_client: httpx.AsyncClient,
    *,
    venue: ExecutionVenue,
) -> WorkloadIdentity:
    if uses_developer_identity(venue):
        return AsyncAzureCliWorkloadIdentity.from_env()
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env="FDAI_MI_CLIENT_ID",
    )


if __name__ == "__main__":
    raise SystemExit(main())
