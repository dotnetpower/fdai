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

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.composition import attach_metric_provider, default_container_from_env
from fdai.core.investigation import InvestigationCoordinator, default_analyzers
from fdai.delivery.analyzer_targets import (
    DEFAULT_MAX_DISCOVERED,
    MAX_DISCOVERED_CEILING,
    AnalyzerTargetResolution,
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
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.delivery.persistence.postgres_idempotency import PostgresIdempotencyStoreConfig
from fdai.delivery.pod_evidence_binding import (
    POD_EVIDENCE_ENV,
    build_pod_lifecycle_evidence_source,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.delivery.trace_continuity_tick import (
    TraceContinuityTickReport,
    TraceContinuityTickRunner,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.venue import (
    ExecutionVenue,
    bus_security_protocol,
    resolve_execution_venue,
    uses_developer_identity,
    uses_workload_identity,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.metric import MetricProvider
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
STATE_STORE_DSN_ENV = "FDAI_STATE_STORE_DSN"
TRACE_TOPOLOGIES_ENV = "FDAI_TRACE_TOPOLOGIES_JSON"
POD_EVIDENCE_JSON_ENV = POD_EVIDENCE_ENV
_TRACE_TOPOLOGY_KEYS = frozenset({"topology_ref", "resource_ref", "expected_hops"})
_MAX_TRACE_TOPOLOGIES = 32
LOOP_INTERVAL_ENV = "FDAI_ANALYZER_INTERVAL_SECONDS"
BUDGET_ENV = "FDAI_ANALYZER_BUDGET_SECONDS"
_DEFAULT_LOOP_INTERVAL_SECONDS = 60
_DEFAULT_TICK_BUDGET_SECONDS = 300
_SCHEDULING_MODES = frozenset({"one_shot", "local_loop", "container_apps_job"})


@dataclass(frozen=True, slots=True)
class AnalyzerJobReport:
    """Preserve the analyzer report and add one bounded continuity report."""

    analyzer: AnalyzerTickReport
    trace_continuity: TraceContinuityTickReport
    target_resolution: AnalyzerTargetResolution

    @property
    def failed(self) -> bool:
        """Return true when either publisher needs a Job retry."""
        return self.analyzer.failed or self.trace_continuity.failed

    def to_dict(
        self,
        *,
        scheduling: str = "one_shot",
        metric_delays: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            **self.analyzer.to_dict(),
            "trace_continuity": self.trace_continuity.to_dict(),
            "target_resolution": self.target_resolution.to_dict(),
            "readiness": self.readiness(
                scheduling=scheduling,
                metric_delays=metric_delays or {},
            ),
        }

    def readiness(
        self,
        *,
        scheduling: str,
        metric_delays: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        """Report availability without turning zero findings into verified health."""

        if scheduling not in _SCHEDULING_MODES:
            raise ValueError("analyzer scheduling mode is invalid")
        target_discovery = (
            "available"
            if self.target_resolution.inventory_consulted or self.target_resolution.configured > 0
            else "unbound"
        )
        metric_access = (
            "unavailable"
            if self.analyzer.analyzer_errors
            or (
                self.analyzer.targets > 0
                and len(self.analyzer.unsupported_targets) == self.analyzer.targets
            )
            else "unverified"
            if self.analyzer.targets == 0
            else "available"
        )
        event_publication = (
            "unavailable"
            if self.analyzer.publish_errors or self.trace_continuity.publish_errors
            else "verified"
            if self.analyzer.published > 0
            or self.analyzer.duplicates_suppressed > 0
            or self.trace_continuity.published > 0
            else "unverified"
        )
        return {
            "scheduling": scheduling,
            "target_discovery": target_discovery,
            "metric_access": metric_access,
            "event_publication": event_publication,
            "metric_source_delays": dict(sorted((metric_delays or {}).items())),
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


def parse_loop_interval(raw: str) -> int:
    """Parse the local/deployed schedule interval with one shared bound."""

    text = raw.strip()
    if not text:
        return _DEFAULT_LOOP_INTERVAL_SECONDS
    try:
        interval = int(text)
    except ValueError as exc:
        raise ValueError(f"{LOOP_INTERVAL_ENV} MUST be a positive integer") from exc
    if not 1 <= interval <= 86_400:
        raise ValueError(f"{LOOP_INTERVAL_ENV} MUST be in [1, 86400]")
    return interval


def parse_tick_budget(raw: str) -> int:
    """Parse the shared local and deployed wall-clock budget."""

    text = raw.strip()
    if not text:
        return _DEFAULT_TICK_BUDGET_SECONDS
    try:
        budget = int(text)
    except ValueError as exc:
        raise ValueError(f"{BUDGET_ENV} MUST be a positive integer") from exc
    if not 1 <= budget <= _DEFAULT_TICK_BUDGET_SECONDS:
        raise ValueError(f"{BUDGET_ENV} MUST be in [1, {_DEFAULT_TICK_BUDGET_SECONDS}]")
    return budget


def metric_source_delays(environ: Mapping[str, str]) -> dict[str, str]:
    """Report configured source-specific delay floors without claiming a live measurement."""

    return {
        "log_analytics": (
            "120-300_seconds" if environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip() else "unbound"
        ),
        "prometheus": (
            "15_seconds_plus_ingestion"
            if environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip()
            else "unbound"
        ),
    }


def resolve_scheduling_mode(raw: str) -> str:
    """Resolve one allowlisted scheduling-mode receipt value."""

    mode = raw.strip() or "one_shot"
    if mode not in _SCHEDULING_MODES:
        raise ValueError("FDAI_ANALYZER_SCHEDULING_MODE is invalid")
    return mode


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


def build_publication_ledger() -> PostgresAnalyzerPublicationLedger:
    """Bind restart-durable publication suppression in every execution venue."""

    dsn = os.environ.get(STATE_STORE_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(
            f"{STATE_STORE_DSN_ENV} is required for duplicate-safe analyzer publication"
        )
    return PostgresAnalyzerPublicationLedger(
        config=PostgresIdempotencyStoreConfig(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        )
    )


def build_analyzer_coordinator(metric_provider: MetricProvider) -> InvestigationCoordinator:
    """Compose every production analyzer this venue can actually ground.

    The Pod lifecycle analyzer joins the pantheon only when this venue declares
    typed Pod evidence. An undeclared source leaves Pod targets reported as
    unsupported, which is the honest outcome: an analyzer with no observations
    would have to invent the completeness its receipt claims.
    """

    return InvestigationCoordinator(
        analyzers=default_analyzers(
            metric_provider,
            pod_lifecycle_evidence=build_pod_lifecycle_evidence_source(),
        )
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
            target_resolution=resolution,
        )

    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not bootstrap_servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is required")
    topic = resolve_finding_topic(os.environ)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    ) as http_client:
        venue = resolve_execution_venue()
        identity = _build_identity(http_client, venue=venue)
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
        bus = _build_finding_bus(
            identity=identity,
            bootstrap_servers=bootstrap_servers,
            venue=venue,
        )
        try:
            if targets:
                analyzer_report = await AnalyzerTickRunner(
                    coordinator=build_analyzer_coordinator(container.metric_provider),
                    event_bus=bus,
                    publication_ledger=build_publication_ledger(),
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
                target_resolution=resolution,
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


def _build_identity(
    http_client: httpx.AsyncClient,
    *,
    venue: ExecutionVenue | None = None,
) -> WorkloadIdentity:
    active_venue = venue or resolve_execution_venue()
    if uses_developer_identity(active_venue):
        return AsyncAzureCliWorkloadIdentity.from_env()
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env="FDAI_MI_CLIENT_ID",
    )


def _build_finding_bus(
    *,
    identity: WorkloadIdentity,
    bootstrap_servers: str,
    venue: ExecutionVenue,
) -> EventHubsKafkaBus:
    return EventHubsKafkaBus(
        identity=identity if uses_workload_identity(venue) else None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=bootstrap_servers,
            security_protocol=bus_security_protocol(venue),
        ),
    )


def _optional(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


async def run_loop(
    *,
    interval_seconds: int,
    max_ticks: int | None = None,
    tick_timeout_seconds: float = _DEFAULT_TICK_BUDGET_SECONDS,
    tick: Callable[[], Awaitable[AnalyzerJobReport]] = run_once,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Run identical one-shot ticks serially and stop on the first failed publication."""

    if not 1 <= interval_seconds <= 86_400:
        raise ValueError("analyzer loop interval_seconds MUST be in [1, 86400]")
    if max_ticks is not None and max_ticks < 1:
        raise ValueError("analyzer loop max_ticks MUST be positive")
    if not 0 < tick_timeout_seconds <= _DEFAULT_TICK_BUDGET_SECONDS:
        raise ValueError("analyzer loop tick_timeout_seconds is out of bounds")
    completed = 0
    while max_ticks is None or completed < max_ticks:
        try:
            report = await asyncio.wait_for(tick(), timeout=tick_timeout_seconds)
        except TimeoutError:
            print("service=local-analyzer event=failed reason=tick_deadline", flush=True)
            return 1
        _emit_report(report, scheduling="local_loop")
        completed += 1
        if report.failed:
            print("service=local-analyzer event=failed", flush=True)
            return 1
        if completed == 1:
            print("service=local-analyzer event=ready", flush=True)
        if max_ticks is not None and completed >= max_ticks:
            return 0
        await sleep(float(interval_seconds))
    return 0


def _emit_report(report: AnalyzerJobReport, *, scheduling: str) -> None:
    summary: dict[str, Any] = report.to_dict(
        scheduling=scheduling,
        metric_delays=metric_source_delays(os.environ),
    )
    _LOGGER.info("analyzer_tick_complete", extra=summary)
    print(json.dumps(summary, sort_keys=True), flush=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounded FDAI analyzer tick.")
    parser.add_argument("--loop", action="store_true", help="Run serial ticks until stopped.")
    parser.add_argument("--interval-seconds", type=int)
    parser.add_argument("--max-ticks", type=int)
    args = parser.parse_args(argv)
    if not args.loop and (args.interval_seconds is not None or args.max_ticks is not None):
        parser.error("--interval-seconds and --max-ticks require --loop")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    tick_budget = parse_tick_budget(os.environ.get(BUDGET_ENV, ""))
    try:
        if args.loop:
            interval = (
                args.interval_seconds
                if args.interval_seconds is not None
                else parse_loop_interval(os.environ.get(LOOP_INTERVAL_ENV, ""))
            )
            print("service=local-analyzer event=starting", flush=True)
            return asyncio.run(
                run_loop(
                    interval_seconds=interval,
                    max_ticks=args.max_ticks,
                    tick_timeout_seconds=tick_budget,
                )
            )
        report = asyncio.run(asyncio.wait_for(run_once(), timeout=tick_budget))
    except KeyboardInterrupt:
        return 130
    _emit_report(
        report,
        scheduling=resolve_scheduling_mode(os.environ.get("FDAI_ANALYZER_SCHEDULING_MODE", "")),
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
