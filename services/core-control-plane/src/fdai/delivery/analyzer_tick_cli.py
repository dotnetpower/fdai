"""One-shot analyzer tick for a Container Apps scheduled Job.

Reads `FDAI_ANALYZER_TARGETS` (a JSON list of ``{resource_id, kind}`` objects),
adds every eligible resource the durable inventory projection already observed
when `FDAI_INVENTORY_DSN` is bound, binds the reference analyzers to whichever
`MetricProvider` composition wired, and publishes one canonical Event per
finding to the analyzer ingest topic.

Exit codes: `0` on a clean pass, including a pass with no resolved target;
`1` when any finding failed to publish, so the Job retries the tick. An
unreadable inventory projection raises instead of degrading to the configured
list alone, so the Job retries rather than silently narrowing its coverage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.composition import attach_metric_provider, default_container_from_env
from fdai.core.investigation import InvestigationCoordinator, default_analyzers
from fdai.delivery.analyzer_targets import (
    DEFAULT_MAX_DISCOVERED,
    MAX_DISCOVERED_CEILING,
    resolve_analyzer_targets,
)
from fdai.delivery.analyzer_tick import (
    DEFAULT_WINDOW_SECONDS,
    AnalyzerTarget,
    AnalyzerTickReport,
    AnalyzerTickRunner,
)
from fdai.delivery.azure.demo_queries import default_metric_queries
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.trace_continuity import (
    AzureTraceContinuitySource,
    TraceTopologyTarget,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.delivery.trace_continuity_tick import (
    TraceContinuityTickReport,
    TraceContinuityTickRunner,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.venue import resolve_execution_venue, uses_developer_identity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.analyzer_tick")
_REPO_ROOT = repo_asset_root()

TARGETS_ENV = "FDAI_ANALYZER_TARGETS"
WINDOW_ENV = "FDAI_ANALYZER_WINDOW_SECONDS"
TRACE_WINDOW_ENV = "FDAI_TRACE_CONTINUITY_WINDOW_SECONDS"
TOPIC_ENV = "FDAI_ANALYZER_TOPIC"
INGRESS_TOPIC_ENV = "KAFKA_TOPIC_EVENTS"
MAX_DISCOVERED_ENV = "FDAI_ANALYZER_MAX_DISCOVERED_TARGETS"
INVENTORY_DSN_ENV = "FDAI_INVENTORY_DSN"
TRACE_TOPOLOGIES_ENV = "FDAI_TRACE_TOPOLOGIES_JSON"
_TRACE_TOPOLOGY_KEYS = frozenset({"topology_ref", "resource_ref", "expected_hops"})
_MAX_TRACE_TOPOLOGIES = 32


@dataclass(frozen=True, slots=True)
class AnalyzerJobReport:
    """Preserve the analyzer report and add one bounded continuity report."""

    analyzer: AnalyzerTickReport
    trace_continuity: TraceContinuityTickReport

    @property
    def failed(self) -> bool:
        """Return true when either publisher needs a Job retry."""
        return self.analyzer.failed or self.trace_continuity.failed

    def to_dict(self) -> dict[str, object]:
        return {
            **self.analyzer.to_dict(),
            "trace_continuity": self.trace_continuity.to_dict(),
        }


def resolve_finding_topic(environ: Mapping[str, str]) -> str:
    """Resolve the topic that actually carries findings into the control loop.

    Findings enter through Huginn's raw ingress, which normalizes them into
    ``object.event`` for the judging agents. Publishing anywhere else reaches no
    consumer, so an unset ingress topic is a configuration error rather than a
    value worth defaulting.
    """

    topic = environ.get(TOPIC_ENV, "").strip() or environ.get(INGRESS_TOPIC_ENV, "").strip()
    if not topic:
        raise RuntimeError(f"{TOPIC_ENV} or {INGRESS_TOPIC_ENV} is required")
    return topic


def parse_targets(raw: str) -> tuple[AnalyzerTarget, ...]:
    """Parse the configured target list.

    An empty or blank value yields no target. Any other malformed value fails
    closed rather than silently analyzing nothing.
    """
    text = raw.strip()
    if not text:
        return ()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{TARGETS_ENV} MUST be a JSON array: {exc}") from exc
    if not isinstance(loaded, list):
        raise ValueError(f"{TARGETS_ENV} MUST be a JSON array")
    targets: list[AnalyzerTarget] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(loaded):
        if not isinstance(item, dict):
            raise ValueError(f"{TARGETS_ENV}[{index}] MUST be an object")
        resource_ref = item.get("resource_id")
        resource_kind = item.get("kind")
        if not isinstance(resource_ref, str) or not isinstance(resource_kind, str):
            raise ValueError(f"{TARGETS_ENV}[{index}] MUST carry string resource_id and kind")
        target = AnalyzerTarget(
            resource_ref=resource_ref.strip(), resource_kind=resource_kind.strip()
        )
        identity = (target.resource_ref, target.resource_kind)
        if identity in seen:
            continue
        seen.add(identity)
        targets.append(target)
    return tuple(targets)


def parse_trace_topologies(raw: str) -> tuple[TraceTopologyTarget, ...]:
    """Parse strict deployment-supplied trace topology declarations."""
    text = raw.strip()
    if not text:
        return ()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{TRACE_TOPOLOGIES_ENV} MUST be a JSON array: {exc}") from exc
    if not isinstance(loaded, list) or len(loaded) > _MAX_TRACE_TOPOLOGIES:
        raise ValueError(
            f"{TRACE_TOPOLOGIES_ENV} MUST be an array with at most {_MAX_TRACE_TOPOLOGIES} items"
        )
    targets: list[TraceTopologyTarget] = []
    seen: set[str] = set()
    for index, item in enumerate(loaded):
        if not isinstance(item, dict) or set(item) != _TRACE_TOPOLOGY_KEYS:
            raise ValueError(
                f"{TRACE_TOPOLOGIES_ENV}[{index}] MUST contain exactly "
                "topology_ref, resource_ref, and expected_hops"
            )
        topology_ref = item["topology_ref"]
        resource_ref = item["resource_ref"]
        expected_hops = item["expected_hops"]
        if (
            not isinstance(topology_ref, str)
            or not isinstance(resource_ref, str)
            or not isinstance(expected_hops, list)
            or any(not isinstance(hop, str) for hop in expected_hops)
        ):
            raise ValueError(f"{TRACE_TOPOLOGIES_ENV}[{index}] has invalid field types")
        target = TraceTopologyTarget(
            topology_ref=topology_ref,
            resource_ref=resource_ref,
            expected_hops=tuple(expected_hops),
        )
        if target.topology_ref in seen:
            raise ValueError(f"{TRACE_TOPOLOGIES_ENV} topology_ref values MUST be unique")
        seen.add(target.topology_ref)
        targets.append(target)
    return tuple(targets)


def parse_window_seconds(raw: str) -> int:
    """Parse the optional analyzer window; a malformed value fails closed."""
    text = raw.strip()
    if not text:
        return DEFAULT_WINDOW_SECONDS
    try:
        window = int(text)
    except ValueError as exc:
        raise ValueError(f"{WINDOW_ENV} MUST be a positive integer") from exc
    if window <= 0:
        raise ValueError(f"{WINDOW_ENV} MUST be a positive integer")
    return window


def resolve_trace_window_seconds(environ: Mapping[str, str], analyzer_window: int) -> int:
    """Resolve the trace-continuity detection window, defaulting to the analyzer window.

    A discontinuity is keyed by its detection window, so one window yields at
    most one distinct finding. Correlating repeats therefore requires a
    detection window several times shorter than the correlation window.
    """

    text = environ.get(TRACE_WINDOW_ENV, "").strip()
    if not text:
        return analyzer_window
    try:
        window = int(text)
    except ValueError as exc:
        raise ValueError(f"{TRACE_WINDOW_ENV} MUST be a positive integer") from exc
    if window <= 0:
        raise ValueError(f"{TRACE_WINDOW_ENV} MUST be a positive integer")
    return window


def parse_max_discovered(raw: str) -> int:
    """Parse the optional inventory-backed target bound; malformed fails closed.

    The upper bound matches the resolver ceiling so a misconfigured deployment
    fails at parse time with the environment key named, not later inside the
    projection read.
    """
    text = raw.strip()
    if not text:
        return DEFAULT_MAX_DISCOVERED
    try:
        bound = int(text)
    except ValueError as exc:
        raise ValueError(f"{MAX_DISCOVERED_ENV} MUST be a positive integer") from exc
    if not 1 <= bound <= MAX_DISCOVERED_CEILING:
        raise ValueError(
            f"{MAX_DISCOVERED_ENV} MUST be an integer in [1, {MAX_DISCOVERED_CEILING}]"
        )
    return bound


def build_inventory_projection() -> PostgresOntologyInstanceStore | None:
    """Bind the durable inventory projection when its database is configured.

    Returns ``None`` when the deployment supplies no inventory DSN, which keeps
    the tick a configured-target-only pass instead of failing a deployment that
    never provisioned the projection.
    """
    dsn = os.environ.get(INVENTORY_DSN_ENV, "").strip()
    if not dsn:
        return None
    catalog_root = _REPO_ROOT / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    return PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        ),
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )


async def run_once() -> AnalyzerJobReport:
    """Compose the tick from the environment and run one analyzer pass."""
    configured = parse_targets(os.environ.get(TARGETS_ENV, ""))
    trace_topologies = parse_trace_topologies(os.environ.get(TRACE_TOPOLOGIES_ENV, ""))
    window_seconds = parse_window_seconds(os.environ.get(WINDOW_ENV, ""))
    trace_window_seconds = resolve_trace_window_seconds(os.environ, window_seconds)
    max_discovered = parse_max_discovered(os.environ.get(MAX_DISCOVERED_ENV, ""))

    resolution = await resolve_analyzer_targets(
        configured=configured,
        store=build_inventory_projection(),
        now=datetime.now(tz=UTC),
        max_discovered=max_discovered,
    )
    _LOGGER.info("analyzer_tick_targets_resolved", extra=resolution.to_dict())
    targets = resolution.targets
    if not targets and not trace_topologies:
        _LOGGER.info("analyzer_tick_no_targets")
        return AnalyzerJobReport(
            analyzer=AnalyzerTickReport(targets=0, findings=0, published=0),
            trace_continuity=_empty_trace_report(),
        )

    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not bootstrap_servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is required")
    topic = resolve_finding_topic(os.environ)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    ) as http_client:
        identity = _build_identity(http_client)
        container = attach_metric_provider(
            default_container_from_env(),
            identity=identity,
            http_client=http_client,
            monitor_workspace_id=_optional("FDAI_MONITOR_WORKSPACE_ID"),
            monitor_queries=default_metric_queries(),
            metrics_api_queries=None,
            prometheus_base_url=_optional("FDAI_PROMETHEUS_ENDPOINT"),
            prometheus_queries=None,
            prometheus_audience=_optional("FDAI_PROMETHEUS_AUDIENCE"),
        )
        bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(bootstrap_servers=bootstrap_servers),
        )
        try:
            if targets:
                analyzer_report = await AnalyzerTickRunner(
                    coordinator=InvestigationCoordinator(
                        analyzers=default_analyzers(container.metric_provider)
                    ),
                    event_bus=bus,
                    window_seconds=window_seconds,
                    topic=topic,
                ).run_once(targets)
            else:
                analyzer_report = AnalyzerTickReport(targets=0, findings=0, published=0)

            if trace_topologies:
                workspace_id = _optional("FDAI_MONITOR_WORKSPACE_ID")
                if workspace_id is None:
                    raise RuntimeError(
                        "FDAI_MONITOR_WORKSPACE_ID is required when "
                        f"{TRACE_TOPOLOGIES_ENV} is configured"
                    )
                trace_report = await TraceContinuityTickRunner(
                    source=AzureTraceContinuitySource(
                        AzureLogAnalyticsQueryProvider(
                            config=AzureLogAnalyticsQueryConfig(workspace_id=workspace_id),
                            identity=identity,
                            http_client=http_client,
                        )
                    ),
                    event_bus=bus,
                    window_seconds=trace_window_seconds,
                    topic=topic,
                ).run_once(trace_topologies)
            else:
                trace_report = _empty_trace_report()
            return AnalyzerJobReport(
                analyzer=analyzer_report,
                trace_continuity=trace_report,
            )
        finally:
            await bus.close()


def _empty_trace_report() -> TraceContinuityTickReport:
    return TraceContinuityTickReport(
        targets=0,
        scenarios=0,
        continuous=0,
        unknown=0,
        findings=0,
        published=0,
    )


def _build_identity(http_client: httpx.AsyncClient) -> WorkloadIdentity:
    if uses_developer_identity(resolve_execution_venue()):
        return AsyncAzureCliWorkloadIdentity.from_env()
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env="FDAI_MI_CLIENT_ID",
    )


def _optional(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def main(argv: list[str] | None = None) -> int:
    del argv
    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    report = asyncio.run(run_once())
    summary: dict[str, Any] = report.to_dict()
    _LOGGER.info("analyzer_tick_complete", extra=summary)
    print(json.dumps(summary, sort_keys=True))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
