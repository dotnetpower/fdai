"""Analyzer tick entry point - out-of-band driver for the metric analyzers.

A Container Apps Job (cron) launches this module once per scheduled fire
(``infra/modules/compute/container-apps/analyzer_tick_job.tf``). It lives
under ``delivery/`` (not ``core/``) because it wires the concrete
:class:`~fdai.delivery.azure.metric_logs.AzureMonitorLogsMetricProvider`
(and optionally :class:`~fdai.delivery.prometheus.PrometheusMetricProvider`)
composition-root adapters - ``core/`` never imports an adapter; a
composition-root entry point does.

Why a periodic tick exists
--------------------------

The Kafka event path (``event-ingest`` -> ``trust-router`` ->
``risk-gate``) is truly real-time (sub-second) because it wakes on
``KubeEvents``, Activity Log changes, and forwarded diagnostic events.
Sampled metrics (``node_cpu_percent``, ``http_429_rate``,
``backend_first_byte_response_time_ms``, ...) have no push channel -
:mod:`fdai.core.investigation.analyzers` reads them through the
:class:`~fdai.shared.providers.metric.MetricProvider` seam pull-style.
Nothing invokes the analyzers periodically upstream, so a metric spike
would sit dark unless something ticks. This CLI is that tick.

Latency envelope
----------------

- ``AzureMonitorLogsMetricProvider`` alone: 2-5 min (Log Analytics
  ingestion lag is the floor).
- ``PrometheusMetricProvider`` (AKS Managed Prometheus, 15 s scrape) as
  the primary + AML as the fallback: ~15-60 s for the AKS-scoped
  metrics; the non-AKS resources still ride the 2-5 min AML floor.
- Combined tick cadence: pick ``FDAI_ANALYZER_TICK_CRON`` on the job
  (e.g. every minute) - the ceiling is the ingestion lag, not the tick.

Target list (``FDAI_ANALYZER_TARGETS``)
---------------------------------------

Explicit rather than inventory-walked: an environment variable carries a
JSON array of ``{"resource_id": "...", "kind": "..."}`` items. This keeps
the tick decoupled from the Inventory seam (which is opt-in and only
bound when a fork wires ARG). Empty / unset -> no-op (exit 0). Malformed
JSON -> exit 3 (safe to page). A fork with a live Inventory MAY switch
to an inventory walk without changing the CLI's public contract.

Upstream-safe binding (mirrors :mod:`fdai.delivery.scheduler_tick_cli`)
----------------------------------------------------------------------

Publishing an :class:`AnalyzerFinding` as an :class:`Event` back onto the
Kafka bus - so the standard ``trust-router`` + risk gate picks it up
without a side channel - requires the concrete event-bus adapter, which
a fork binds at the composition root. Upstream this entry point runs a
**shadow dry-run**: it invokes the analyzers, logs the findings, and
exits ``0`` without publishing. A fork swaps the dry-run for a call to
its :class:`~fdai.shared.providers.event_bus.EventBus` producer.

Exit codes
----------

- ``0`` - the tick completed (findings logged), or no target list is
  configured (nothing to do upstream).
- ``3`` - unexpected error (invalid config / provider crash); safe to
  page.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import httpx

from fdai.composition import Container, default_container_from_env
from fdai.core.investigation import (
    KIND_AKS,
    AnalyzerFinding,
    InvestigationCoordinator,
    InvestigationRequest,
    default_analyzers,
)
from fdai.core.readiness import (
    DetectionObservationStatus,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    detection_readiness_state_key,
)
from fdai.core.report_feed import signals_from_investigation
from fdai.delivery.azure.demo_queries import METRIC_POD_RESTARTS
from fdai.delivery.event_publisher import EventPublisherContext
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.metric import MetricProvider, MetricQuery, NoopMetricProvider
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.delivery.analyzer_tick_cli")

_ENV_TARGETS = "FDAI_ANALYZER_TARGETS"
_ENV_INVENTORY_DSN = "FDAI_INVENTORY_DSN"
_ENV_WINDOW = "FDAI_ANALYZER_WINDOW_SECONDS"
_ENV_BUDGET = "FDAI_ANALYZER_BUDGET_SECONDS"

_DEFAULT_WINDOW_SECONDS = 300.0
_DEFAULT_BUDGET_SECONDS = 60.0
_READINESS_EVIDENCE_SECONDS = 600
_PIPELINE_FRESHNESS_SECONDS = 900


@dataclass(frozen=True, slots=True)
class _Target:
    """One (resource_ref, resource_kind) pair to investigate this tick."""

    resource_ref: str
    resource_kind: str
    discovery_status: DetectionObservationStatus = DetectionObservationStatus.PASSED
    discovery_source: str = "target.configuration"
    discovery_detail: str | None = None


def _load_targets() -> tuple[_Target, ...]:
    """Parse ``FDAI_ANALYZER_TARGETS`` into a validated tuple.

    Empty / unset returns ``()`` (the caller no-ops). Malformed JSON,
    non-list shape, or a missing required field raises :class:`ValueError`
    so the caller exits ``3`` instead of silently doing nothing.
    """
    raw = os.environ.get(_ENV_TARGETS, "").strip()
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{_ENV_TARGETS} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{_ENV_TARGETS} MUST be a JSON array of target objects")
    targets: list[_Target] = []
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"{_ENV_TARGETS}[{i}] MUST be an object")
        resource_ref = item.get("resource_id")
        resource_kind = item.get("kind")
        if not isinstance(resource_ref, str) or not resource_ref:
            raise ValueError(f"{_ENV_TARGETS}[{i}].resource_id MUST be a non-empty string")
        if not isinstance(resource_kind, str) or not resource_kind:
            raise ValueError(f"{_ENV_TARGETS}[{i}].kind MUST be a non-empty string")
        targets.append(_Target(resource_ref=resource_ref, resource_kind=resource_kind))
    return tuple(targets)


def _positive_float(env_name: str, default: float) -> float:
    """Read a positive float from env or return the default."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} MUST be a positive number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{env_name} MUST be a positive number, got {value}")
    return value


async def _run_tick(
    container: Container,
    targets: tuple[_Target, ...],
    *,
    event_bus: EventBus | None = None,
    runtime_values: Mapping[str, object] | None = None,
) -> int:
    """Invoke the reference analyzers against ``targets`` once."""
    if isinstance(container.metric_provider, NoopMetricProvider):
        _LOGGER.warning(
            "analyzer_tick_noop_provider",
            extra={
                "reason": (
                    "container.metric_provider is NoopMetricProvider - "
                    "no live telemetry backend is bound. Set "
                    "FDAI_MONITOR_WORKSPACE_ID (or wire Prometheus) "
                    "to make the analyzers see real metrics."
                ),
            },
        )
        # Fail-soft: still run so the wiring itself is exercised, but
        # every analyzer will abstain because the noop provider returns
        # no samples. Exit 0 - not an error, just not useful.
    coordinator = InvestigationCoordinator(
        analyzers=default_analyzers(container.metric_provider),
    )
    request = InvestigationRequest(
        requested_by="analyzer-tick",
        resources=tuple((t.resource_ref, t.resource_kind) for t in targets),
        window_seconds=_runtime_number(
            runtime_values,
            "analyzer.window_seconds",
            _ENV_WINDOW,
            _DEFAULT_WINDOW_SECONDS,
        ),
        budget_seconds=_runtime_number(
            runtime_values,
            "analyzer.budget_seconds",
            _ENV_BUDGET,
            _DEFAULT_BUDGET_SECONDS,
        ),
    )
    report = await coordinator.investigate(request)
    await _persist_report_signals(report)
    _LOGGER.info(
        "analyzer_tick_report",
        extra={
            "investigation_id": report.investigation_id,
            "outcome": report.outcome.value,
            "targets": len(targets),
            "findings": len(report.findings),
            "elapsed_seconds": report.elapsed_seconds,
            "analyzer_errors": len(report.analyzer_errors),
        },
    )
    for finding in report.findings:
        _LOGGER.info(
            "analyzer_tick_finding",
            extra={
                "resource_ref": finding.resource_ref,
                "resource_kind": finding.resource_kind,
                "signal": finding.signal,
                "severity": finding.severity.value,
                "observation": finding.observation,
                "occurred_at": finding.occurred_at.isoformat(),
            },
        )
        if event_bus is not None:
            event = _finding_event(report.investigation_id, finding)
            await event_bus.publish(
                container.config.kafka.topic_events,
                finding.resource_ref,
                event.model_dump(mode="json"),
            )
    return 0


async def _publish_detection_readiness(
    *,
    targets: tuple[_Target, ...],
    metric_provider: MetricProvider,
    event_bus: EventBus,
    topic: str,
    state_store: StateStore | None,
    observed_at: datetime,
) -> int:
    """Publish bounded AKS readiness facts to Huginn's raw ingress topic."""
    published = 0
    for target in targets:
        if target.resource_kind != KIND_AKS:
            continue
        observations = await _aks_detection_observations(
            target,
            metric_provider=metric_provider,
            state_store=state_store,
            observed_at=observed_at,
        )
        resource_digest = hashlib.sha256(target.resource_ref.encode("utf-8")).hexdigest()
        pass_id = hashlib.sha256(
            f"{resource_digest}|{observed_at.isoformat()}".encode()
        ).hexdigest()
        for observation in observations:
            identity = f"detection-readiness:{observation.evidence_digest}"
            event = Event(
                schema_version="1.0.0",
                event_id=uuid5(NAMESPACE_URL, identity),
                idempotency_key=identity,
                correlation_id=f"detection-readiness:{resource_digest}",
                source="fdai.delivery.analyzer_tick",
                event_type="detection.readiness.observed",
                resource_ref=target.resource_ref,
                payload={
                    "detection_readiness": {
                        "dimension": observation.dimension.value,
                        "status": observation.status.value,
                        "observed_at": observation.observed_at.isoformat(),
                        "expires_at": observation.expires_at.isoformat(),
                        "source": observation.source,
                        "evidence_digest": observation.evidence_digest,
                        "pass_id": pass_id,
                        **(
                            {"detail_code": observation.detail_code}
                            if observation.detail_code is not None
                            else {}
                        ),
                    }
                },
                detected_at=observation.observed_at,
                ingested_at=observation.observed_at,
                incident_correlation=IncidentCorrelation.NONE,
                mode=Mode.SHADOW,
            )
            await event_bus.publish(topic, target.resource_ref, event.model_dump(mode="json"))
            published += 1
    return published


async def _aks_detection_observations(
    target: _Target,
    *,
    metric_provider: MetricProvider,
    state_store: StateStore | None,
    observed_at: datetime,
) -> tuple[DetectionReadinessObservation, ...]:
    statuses: dict[
        DetectionReadinessDimension,
        tuple[DetectionObservationStatus, str, str | None],
    ] = {
        DetectionReadinessDimension.DISCOVERED: (
            target.discovery_status,
            target.discovery_source,
            target.discovery_detail,
        ),
        DetectionReadinessDimension.DETECTOR_BOUND: (
            DetectionObservationStatus.PASSED,
            "fdai.catalog",
            None,
        ),
        DetectionReadinessDimension.ACTION_GOVERNED: (
            DetectionObservationStatus.PASSED,
            "fdai.governance",
            None,
        ),
    }
    metric_status: DetectionObservationStatus
    metric_detail: str | None
    telemetry_status: DetectionObservationStatus
    telemetry_detail: str | None
    if isinstance(metric_provider, NoopMetricProvider):
        metric_status = DetectionObservationStatus.UNAVAILABLE
        metric_detail = "metric_provider_unconfigured"
        telemetry_status = DetectionObservationStatus.UNAVAILABLE
        telemetry_detail = metric_detail
    else:
        try:
            query = MetricQuery(
                metric_name=METRIC_POD_RESTARTS,
                labels={"resource_id": target.resource_ref},
                since=observed_at - timedelta(seconds=_READINESS_EVIDENCE_SECONDS),
                until=observed_at,
                aggregation="max",
            )
            has_sample = False
            async for _point in metric_provider.query(query):
                has_sample = True
                break
            metric_status = DetectionObservationStatus.PASSED
            metric_detail = None
            telemetry_status = (
                DetectionObservationStatus.PASSED
                if has_sample
                else DetectionObservationStatus.UNAVAILABLE
            )
            telemetry_detail = None if has_sample else "telemetry_sample_missing"
        except Exception:  # noqa: BLE001 - provider details stay behind sanitized status
            metric_status = DetectionObservationStatus.UNAVAILABLE
            metric_detail = "metric_query_unavailable"
            telemetry_status = DetectionObservationStatus.UNAVAILABLE
            telemetry_detail = metric_detail
    statuses[DetectionReadinessDimension.COLLECTOR_CONFIGURED] = (
        metric_status,
        "metric.provider",
        metric_detail,
    )
    statuses[DetectionReadinessDimension.TELEMETRY_OBSERVED] = (
        telemetry_status,
        "metric.sample",
        telemetry_detail,
    )

    pipeline_status = DetectionObservationStatus.UNAVAILABLE
    pipeline_detail: str | None = "prior_snapshot_missing"
    if state_store is not None:
        prior = await state_store.read_state(detection_readiness_state_key(target.resource_ref))
        prior_generated = prior.get("generated_at") if prior is not None else None
        if isinstance(prior_generated, str):
            try:
                generated_at = datetime.fromisoformat(prior_generated.replace("Z", "+00:00"))
            except ValueError:
                generated_at = None
            if (
                generated_at is not None
                and generated_at.tzinfo is not None
                and timedelta(0)
                <= observed_at - generated_at
                <= timedelta(seconds=_PIPELINE_FRESHNESS_SECONDS)
            ):
                pipeline_status = DetectionObservationStatus.PASSED
                pipeline_detail = None
            else:
                pipeline_detail = "prior_snapshot_stale"
    statuses[DetectionReadinessDimension.PIPELINE_OBSERVED] = (
        pipeline_status,
        "muninn.snapshot",
        pipeline_detail,
    )

    expires_at = observed_at + timedelta(seconds=_READINESS_EVIDENCE_SECONDS)
    observations: list[DetectionReadinessObservation] = []
    resource_digest = hashlib.sha256(target.resource_ref.encode("utf-8")).hexdigest()
    for dimension in DetectionReadinessDimension:
        status, source, detail = statuses[dimension]
        material = "|".join(
            (
                resource_digest,
                dimension.value,
                status.value,
                detail or "passed",
                observed_at.isoformat(),
            )
        )
        observations.append(
            DetectionReadinessObservation(
                resource_ref=target.resource_ref,
                dimension=dimension,
                status=status,
                observed_at=observed_at,
                expires_at=expires_at,
                source=source,
                evidence_digest=hashlib.sha256(material.encode("utf-8")).hexdigest(),
                detail_code=detail,
            )
        )
    return tuple(observations)


async def _persist_report_signals(report: object) -> None:
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return
    from fdai.core.investigation import InvestigationReport
    from fdai.delivery.persistence import (
        PostgresReportSignalStore,
        PostgresReportSignalStoreConfig,
    )

    if not isinstance(report, InvestigationReport):
        raise TypeError("report MUST be an InvestigationReport")
    store = PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(dsn=dsn))
    await store.record_many(signals_from_investigation(report))


def _finding_event(investigation_id: str, finding: AnalyzerFinding) -> Event:
    resource_ref = finding.resource_ref
    signal = finding.signal
    occurred_at = finding.occurred_at
    identity = f"{investigation_id}:{resource_ref}:{signal}:{occurred_at.isoformat()}"
    return Event(
        schema_version="1.0.0",
        event_id=uuid5(NAMESPACE_URL, f"fdai.analyzer://{identity}"),
        idempotency_key=f"analyzer:{identity}",
        source="fdai.delivery.analyzer_tick",
        event_type=f"analyzer.{signal}",
        resource_ref=resource_ref,
        payload={
            "resource": {
                "resource_id": resource_ref,
                "type": finding.resource_kind,
            },
            "finding": {
                "signal": signal,
                "severity": finding.severity.value,
                "observation": finding.observation,
            },
        },
        detected_at=occurred_at,
        ingested_at=occurred_at,
        mode=Mode.SHADOW,
    )


async def _tick() -> int:
    targets = _load_targets()
    if not targets:
        targets = await _load_inventory_targets()
    if not targets:
        _LOGGER.info(
            "analyzer_tick_no_targets",
            extra={"reason": f"{_ENV_TARGETS} and active inventory are empty"},
        )
        return 0
    from fdai.delivery.runtime_settings import runtime_settings_service_from_env

    runtime_values = await runtime_settings_service_from_env(os.environ).effective_values()
    container = default_container_from_env()
    monitor_workspace_id = os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip() or None
    prometheus_base_url = os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip() or None
    prometheus_audience = os.environ.get("FDAI_PROMETHEUS_AUDIENCE", "").strip() or None
    http_client: httpx.AsyncClient | None = None
    readiness_store: StateStore | None = None
    try:
        if monitor_workspace_id is not None or prometheus_base_url is not None:
            from fdai.composition import attach_metric_provider
            from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
            )
            container = attach_metric_provider(
                container,
                identity=ManagedIdentityWorkloadIdentity(http_client=http_client),
                http_client=http_client,
                monitor_workspace_id=monitor_workspace_id,
                monitor_queries=None,
                metrics_api_queries=None,
                prometheus_base_url=prometheus_base_url,
                prometheus_queries=None,
                prometheus_audience=prometheus_audience,
            )
        dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
        if dsn:
            from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

            readiness_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
        async with EventPublisherContext(kafka=container.config.kafka) as event_bus:
            await _publish_detection_readiness(
                targets=targets,
                metric_provider=container.metric_provider,
                event_bus=event_bus,
                topic=container.config.kafka.topic_events,
                state_store=readiness_store,
                observed_at=datetime.now(tz=UTC),
            )
            return await _run_tick(
                container,
                targets,
                event_bus=event_bus,
                runtime_values=runtime_values,
            )
    finally:
        if http_client is not None:
            await http_client.aclose()


def _runtime_number(
    values: Mapping[str, object] | None,
    key: str,
    env_name: str,
    default: float,
) -> float:
    if values is None:
        return _positive_float(env_name, default)
    value = values.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"effective runtime setting {key} is invalid")
    return float(value)


async def _load_inventory_targets() -> tuple[_Target, ...]:
    dsn = (
        os.environ.get(_ENV_INVENTORY_DSN, "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        return ()
    from fdai.delivery.persistence.postgres_inventory_snapshot import (
        PostgresInventoryGraphProvider,
        PostgresInventorySnapshotStoreConfig,
    )

    graph = await PostgresInventoryGraphProvider(
        config=PostgresInventorySnapshotStoreConfig(dsn=dsn)
    )(None, 0, ())
    resources = graph.get("resources")
    discovery_status, discovery_detail = _inventory_discovery_evidence(graph)
    return _targets_from_inventory(
        resources if isinstance(resources, list) else [],
        discovery_status=discovery_status,
        discovery_detail=discovery_detail,
    )


def _inventory_discovery_evidence(
    graph: Mapping[str, object],
) -> tuple[DetectionObservationStatus, str | None]:
    if graph.get("freshness") != "fresh":
        return DetectionObservationStatus.UNAVAILABLE, "inventory_snapshot_stale"
    if graph.get("degraded") is True:
        return DetectionObservationStatus.UNAVAILABLE, "inventory_coverage_degraded"
    return DetectionObservationStatus.PASSED, None


def _targets_from_inventory(
    resources: list[object],
    *,
    discovery_status: DetectionObservationStatus = DetectionObservationStatus.PASSED,
    discovery_detail: str | None = None,
) -> tuple[_Target, ...]:
    kind_by_type = {
        "kubernetes-cluster": "aks_cluster",
        "network.application-gateway": "application_gateway",
        "api-gateway": "api_management",
        "mysql-server": "mysql_flexible_server",
        "llm-endpoint": "azure_openai",
    }
    targets: list[_Target] = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        resource_ref = item.get("id")
        resource_type = item.get("type")
        kind = kind_by_type.get(str(resource_type))
        if isinstance(resource_ref, str) and resource_ref and kind is not None:
            targets.append(
                _Target(
                    resource_ref=resource_ref,
                    resource_kind=kind,
                    discovery_status=discovery_status,
                    discovery_source="inventory.snapshot",
                    discovery_detail=discovery_detail,
                )
            )
    return tuple(targets)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return asyncio.run(_tick())
    except Exception:  # noqa: BLE001 - top-level job guard; log + non-zero exit
        _LOGGER.exception("analyzer_tick_failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())
