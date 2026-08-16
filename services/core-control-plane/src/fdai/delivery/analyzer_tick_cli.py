"""One-shot analyzer tick for a Container Apps scheduled Job.

Reads `FDAI_ANALYZER_TARGETS` (a JSON list of ``{resource_id, kind}`` objects),
adds every eligible resource the durable inventory projection already observed
when `FDAI_DATABASE_URL` is bound, binds the reference analyzers to whichever
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from fdai.composition import attach_metric_provider, default_container_from_env
from fdai.core.investigation import InvestigationCoordinator, default_analyzers
from fdai.delivery.analyzer_targets import (
    DEFAULT_MAX_DISCOVERED,
    resolve_analyzer_targets,
)
from fdai.delivery.analyzer_tick import (
    ANALYZER_EVENT_TOPIC,
    DEFAULT_WINDOW_SECONDS,
    AnalyzerTarget,
    AnalyzerTickReport,
    AnalyzerTickRunner,
)
from fdai.delivery.azure.demo_queries import default_metric_queries
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.analyzer_tick")
_REPO_ROOT = Path(__file__).resolve().parents[5]

TARGETS_ENV = "FDAI_ANALYZER_TARGETS"
WINDOW_ENV = "FDAI_ANALYZER_WINDOW_SECONDS"
TOPIC_ENV = "FDAI_ANALYZER_TOPIC"
MAX_DISCOVERED_ENV = "FDAI_ANALYZER_MAX_DISCOVERED_TARGETS"
DATABASE_ENV = "FDAI_DATABASE_URL"


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


def parse_max_discovered(raw: str) -> int:
    """Parse the optional inventory-backed target bound; malformed fails closed."""
    text = raw.strip()
    if not text:
        return DEFAULT_MAX_DISCOVERED
    try:
        bound = int(text)
    except ValueError as exc:
        raise ValueError(f"{MAX_DISCOVERED_ENV} MUST be a positive integer") from exc
    if bound <= 0:
        raise ValueError(f"{MAX_DISCOVERED_ENV} MUST be a positive integer")
    return bound


def build_inventory_projection() -> PostgresOntologyInstanceStore | None:
    """Bind the durable inventory projection when a database is configured.

    Returns ``None`` when no database is bound, which keeps the tick a
    configured-target-only pass instead of failing a deployment that never
    provisioned the projection.
    """
    dsn = os.environ.get(DATABASE_ENV, "").strip()
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


async def run_once() -> AnalyzerTickReport:
    """Compose the tick from the environment and run one analyzer pass."""
    configured = parse_targets(os.environ.get(TARGETS_ENV, ""))
    window_seconds = parse_window_seconds(os.environ.get(WINDOW_ENV, ""))
    max_discovered = parse_max_discovered(os.environ.get(MAX_DISCOVERED_ENV, ""))

    resolution = await resolve_analyzer_targets(
        configured=configured,
        store=build_inventory_projection(),
        now=datetime.now(tz=UTC),
        max_discovered=max_discovered,
    )
    _LOGGER.info("analyzer_tick_targets_resolved", extra=resolution.to_dict())
    targets = resolution.targets
    if not targets:
        _LOGGER.info("analyzer_tick_no_targets")
        return AnalyzerTickReport(targets=0, findings=0, published=0)

    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not bootstrap_servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is required")
    topic = os.environ.get(TOPIC_ENV, "").strip() or ANALYZER_EVENT_TOPIC

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
            runner = AnalyzerTickRunner(
                coordinator=InvestigationCoordinator(
                    analyzers=default_analyzers(container.metric_provider)
                ),
                event_bus=bus,
                window_seconds=window_seconds,
                topic=topic,
            )
            return await runner.run_once(targets)
        finally:
            await bus.close()


def _build_identity(http_client: httpx.AsyncClient) -> WorkloadIdentity:
    venue = os.environ.get("FDAI_EXECUTION_VENUE", "deployed").strip()
    if venue not in {"local", "deployed"}:
        raise ValueError("FDAI_EXECUTION_VENUE MUST be local or deployed")
    if venue == "local":
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
