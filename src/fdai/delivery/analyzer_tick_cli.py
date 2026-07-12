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
import json
import logging
import os
import sys
from dataclasses import dataclass

from fdai.composition import default_container_from_env
from fdai.composition._helpers import Container
from fdai.core.investigation import (
    InvestigationCoordinator,
    InvestigationRequest,
    default_analyzers,
)
from fdai.shared.providers.metric import NoopMetricProvider

_LOGGER = logging.getLogger("fdai.delivery.analyzer_tick_cli")

_ENV_TARGETS = "FDAI_ANALYZER_TARGETS"
_ENV_WINDOW = "FDAI_ANALYZER_WINDOW_SECONDS"
_ENV_BUDGET = "FDAI_ANALYZER_BUDGET_SECONDS"

_DEFAULT_WINDOW_SECONDS = 300.0
_DEFAULT_BUDGET_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class _Target:
    """One (resource_ref, resource_kind) pair to investigate this tick."""

    resource_ref: str
    resource_kind: str


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


async def _run_tick(container: Container, targets: tuple[_Target, ...]) -> int:
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
        window_seconds=_positive_float(_ENV_WINDOW, _DEFAULT_WINDOW_SECONDS),
        budget_seconds=_positive_float(_ENV_BUDGET, _DEFAULT_BUDGET_SECONDS),
    )
    report = await coordinator.investigate(request)
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
    # Upstream does not publish: a fork binds an EventBus and swaps this
    # dry-run for a producer that re-injects each finding as an Event
    # onto the ingest topic. The standard trust-router + risk-gate then
    # governs any resulting action; the tick never executes a change.
    return 0


async def _tick() -> int:
    targets = _load_targets()
    if not targets:
        _LOGGER.info("analyzer_tick_no_targets", extra={"reason": f"{_ENV_TARGETS} unset"})
        return 0
    container = default_container_from_env()
    return await _run_tick(container, targets)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return asyncio.run(_tick())
    except Exception:  # noqa: BLE001 - top-level job guard; log + non-zero exit
        _LOGGER.exception("analyzer_tick_failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())
