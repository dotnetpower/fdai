"""One-shot analyzer tick for a Container Apps scheduled Job.

Reads `FDAI_ANALYZER_TARGETS` (a JSON list of
``{resource_id, kind, provider_resource_id?}`` objects), adds every eligible
resource the durable inventory projection already observed when
`FDAI_INVENTORY_DSN` is bound, binds the reference analyzers to whichever
`MetricProvider` composition wired, and publishes one canonical Event per
finding to the analyzer ingest topic.

One-shot and bounded-loop exit codes are `0` after a clean final pass,
including a pass with no resolved target, and `1` when the final pass is
incomplete. The unbounded local loop remains alive across a failed pass,
target-resolution outage, tick deadline, or run-receipt persistence outage,
withholds readiness, and retries on the next interval. Configuration and
programming errors still propagate. An unreadable inventory projection raises
instead of degrading to the configured list alone.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.composition import attach_metric_provider, default_container_from_env
from fdai.delivery.analyzer_receipt_store import StateStoreAnalyzerReceiptStore
from fdai.delivery.analyzer_run_receipt import (
    AnalyzerRunReceiptPersistenceError,
    record_analyzer_run_receipt,
)
from fdai.delivery.analyzer_targets import (
    AnalyzerResourceTypeResolution,
    AnalyzerTargetResolution,
    AnalyzerTargetResolutionError,
    resolve_analyzer_targets,
)
from fdai.delivery.analyzer_telemetry_admission import discovered_telemetry_holds
from fdai.delivery.analyzer_tick import (
    DEFAULT_PUBLICATION_WINDOW_SECONDS,
    AnalyzerPublicationStatus,
    AnalyzerTickReport,
    AnalyzerTickRunner,
)
from fdai.delivery.analyzer_tick_cli_composition import (
    build_analyzer_coordinator,
    build_decision_evidence_admission_provider,
    build_inventory_sources,
    build_lifecycle_recorder,
    build_publication_ledger,
    build_receipt_store,
)
from fdai.delivery.analyzer_tick_cli_config import (
    BUDGET_ENV,
    DEFAULT_MAX_DISCOVERED,
    DEFAULT_TICK_BUDGET_SECONDS,
    DEFAULT_TRACE_LOOKBACK_SECONDS,
    INGRESS_TOPIC_ENV,
    INVENTORY_DSN_ENV,
    LOOP_INTERVAL_ENV,
    MAX_DISCOVERED_ENV,
    POD_EVIDENCE_JSON_ENV,
    STATE_STORE_DSN_ENV,
    TARGETS_ENV,
    TOPIC_ENV,
    TRACE_LOOKBACK_ENV,
    TRACE_TOPOLOGIES_ENV,
    TRACE_WINDOW_ENV,
    WINDOW_ENV,
    metric_source_delays,
    parse_loop_interval,
    parse_max_discovered,
    parse_targets,
    parse_tick_budget,
    parse_trace_topologies,
    parse_window_seconds,
    resolve_finding_topic,
    resolve_scheduling_mode,
    resolve_trace_lookback_seconds,
    resolve_trace_window_seconds,
)
from fdai.delivery.analyzer_tick_cli_config import (
    SCHEDULING_MODES as _SCHEDULING_MODES,
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
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.trace_continuity_tick import (
    TraceContinuityTickReport,
    TraceContinuityTickRunner,
)
from fdai.runtime.venue import (
    ExecutionVenue,
    bus_security_protocol,
    resolve_execution_venue,
    uses_developer_identity,
    uses_workload_identity,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.analyzer_tick")
_TARGET_RESOLUTION_RETRY_SECONDS = 5.0

_PUBLICATION_STATES = tuple(item.value for item in AnalyzerPublicationStatus)


@dataclass(frozen=True, slots=True)
class AnalyzerJobReport:
    """Preserve the analyzer report and add one bounded continuity report."""

    analyzer: AnalyzerTickReport
    trace_continuity: TraceContinuityTickReport
    target_resolution: AnalyzerTargetResolution

    @property
    def failed(self) -> bool:
        """Return true when either publisher needs a Job retry."""
        unusable_targets = self.target_resolution.inventory_consulted and (
            self.target_resolution.truncated
            or (not self.target_resolution.source_complete and not self.target_resolution.targets)
        )
        return self.analyzer.failed or self.trace_continuity.failed or unusable_targets

    def to_dict(
        self,
        *,
        scheduling: str = "one_shot",
        metric_delays: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            **self.analyzer.to_dict(),
            "coverage": self.coverage(),
            "trace_continuity": self.trace_continuity.to_dict(),
            "target_resolution": self.target_resolution.to_dict(),
            "readiness": self.readiness(
                scheduling=scheduling,
                metric_delays=metric_delays or {},
            ),
        }

    def coverage(self) -> dict[str, object]:
        """Return strictly reconciled cross-resource evaluation coverage."""

        if self.target_resolution.inventory_consulted:
            if self.target_resolution.truncated:
                return _unavailable_coverage("resource_discovery_truncated")
        targets = {target.resource_ref: target for target in self.target_resolution.targets}
        if len(targets) != len(self.target_resolution.targets):
            return _unavailable_coverage("selected_resource_identity_duplicate")
        unavailable_reason = self.target_resolution.coverage_unavailable_reason
        if (
            unavailable_reason is None
            and self.target_resolution.targets
            and not self.target_resolution.resource_types
        ):
            unavailable_reason = "resource_type_evidence_absent"
        if unavailable_reason is not None:
            return _unavailable_coverage(unavailable_reason)

        if any(target.resource_type is None for target in targets.values()):
            return _unavailable_coverage("resource_type_evidence_absent")

        findings_by_resource = Counter(finding.resource_ref for finding in self.analyzer.receipts)
        if sum(findings_by_resource.values()) != self.analyzer.findings:
            return _unavailable_coverage("finding_receipts_absent")
        receipt_by_key = {receipt.idempotency_key: receipt for receipt in self.analyzer.receipts}
        if len(receipt_by_key) != len(self.analyzer.receipts):
            return _unavailable_coverage("finding_receipt_identity_duplicate")
        if set(findings_by_resource) - set(targets):
            return _unavailable_coverage("finding_target_unselected")

        unsupported = Counter(self.analyzer.unsupported_targets)
        evaluation_errors = Counter(
            resource_ref for resource_ref, _error in self.analyzer.analyzer_errors
        )
        error_codes_by_resource: dict[str, set[str]] = defaultdict(set)
        for resource_ref, error in self.analyzer.analyzer_errors:
            error_codes_by_resource[resource_ref].add(
                "analyzer_timeout" if error == "timeout" else "analyzer_failure"
            )
        if (set(unsupported) | set(evaluation_errors)) - set(targets):
            return _unavailable_coverage("evaluation_target_unselected")

        delivery_errors: Counter[str] = Counter()
        unattributed_error_count = 0
        unattributed_error_codes: set[str] = set()
        for errors, code in (
            (self.analyzer.publish_errors, "publication_failure"),
            (self.analyzer.receipt_errors, "receipt_persistence_failure"),
        ):
            for key, _error in errors:
                receipt = receipt_by_key.get(key)
                if receipt is None:
                    unattributed_error_count += 1
                    unattributed_error_codes.add(code)
                else:
                    delivery_errors[receipt.resource_ref] += 1
                    error_codes_by_resource[receipt.resource_ref].add(code)

        publication_by_resource: dict[str, Counter[str]] = defaultdict(Counter)
        for receipt in self.analyzer.receipts:
            publication_by_resource[receipt.resource_ref][receipt.publication.value] += 1

        resources: list[dict[str, object]] = []
        for target in sorted(
            targets.values(),
            key=lambda item: (str(item.resource_type), item.resource_ref),
        ):
            resource_ref = target.resource_ref
            finding_count = findings_by_resource[resource_ref]
            evaluation_error_count = evaluation_errors[resource_ref]
            unsupported_count = unsupported[resource_ref]
            evaluation_state = (
                "unsupported"
                if unsupported_count
                else "evaluation_error"
                if evaluation_error_count
                else "finding"
                if finding_count
                else "evaluated_no_finding"
            )
            resources.append(
                {
                    "resource_ref": resource_ref,
                    "resource_type": str(target.resource_type),
                    "resource_kind": target.resource_kind,
                    "evaluation_state": evaluation_state,
                    "finding_count": finding_count,
                    "unsupported_count": unsupported_count,
                    "error_count": evaluation_error_count + delivery_errors[resource_ref],
                    "error_codes": sorted(error_codes_by_resource[resource_ref]),
                    "publication_counts": _publication_counts(
                        publication_by_resource[resource_ref]
                    ),
                }
            )

        try:
            by_resource_type = _coverage_by_resource_type(
                self.target_resolution.resource_types,
                resources,
            )
        except ValueError:
            return _unavailable_coverage("resource_type_totals_unreconciled")
        publication_counts = _publication_counts(
            Counter(receipt.publication.value for receipt in self.analyzer.receipts)
        )
        evaluated_count = sum(
            1
            for resource in resources
            if resource["evaluation_state"] in {"evaluated_no_finding", "finding"}
        )
        error_count = (
            len(self.analyzer.analyzer_errors)
            + len(self.analyzer.publish_errors)
            + len(self.analyzer.receipt_errors)
        )
        coverage: dict[str, object] = {
            "schema_version": "1.1.0",
            "status": "available",
            "unavailable_reason": None,
            "candidate_count": sum(
                item.candidate_count for item in self.target_resolution.resource_types
            ),
            "selected_count": len(resources),
            "evaluated_count": evaluated_count,
            "held_count": sum(item.held_count for item in self.target_resolution.resource_types),
            "finding_count": sum(findings_by_resource.values()),
            "unsupported_count": sum(unsupported.values()),
            "error_count": error_count,
            "unattributed_error_count": unattributed_error_count,
            "unattributed_error_codes": sorted(unattributed_error_codes),
            "publication_counts": publication_counts,
            "resource_types": by_resource_type,
            "resources": resources,
            "cause_claim_supported": False,
            "execution_authority": False,
        }
        return coverage

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
            "unavailable"
            if self.target_resolution.inventory_consulted
            and (
                self.target_resolution.truncated
                or (
                    not self.target_resolution.source_complete
                    and not self.target_resolution.targets
                )
            )
            else "available"
            if self.target_resolution.inventory_consulted or self.target_resolution.configured > 0
            else "unbound"
        )
        metric_access = (
            "unavailable"
            if self.analyzer.analyzer_errors or self.analyzer.unsupported_targets
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


def _unavailable_coverage(reason: str) -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "status": "unavailable",
        "unavailable_reason": reason,
        "cause_claim_supported": False,
        "execution_authority": False,
    }


def _publication_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return {state: counts.get(state, 0) for state in _PUBLICATION_STATES}


def _coverage_by_resource_type(
    resolutions: tuple[AnalyzerResourceTypeResolution, ...],
    resources: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: dict[str, dict[str, object]] = {
        resolution.resource_type: {
            "resource_type": resolution.resource_type,
            "candidate_count": resolution.candidate_count,
            "selected_count": resolution.selected_count,
            "evaluated_count": 0,
            "held_count": resolution.held_count,
            "held_reason_counts": dict(resolution.held_reason_counts),
            "finding_count": 0,
            "unsupported_count": 0,
            "error_count": 0,
            "error_codes": [],
            "publication_counts": _publication_counts({}),
        }
        for resolution in resolutions
    }
    observed_selected: Counter[str] = Counter()
    for resource in resources:
        resource_type = resource.get("resource_type")
        evaluation_state = resource.get("evaluation_state")
        finding_count = resource.get("finding_count")
        unsupported_count = resource.get("unsupported_count")
        error_count = resource.get("error_count")
        error_codes = resource.get("error_codes")
        publication_counts = resource.get("publication_counts")
        if (
            not isinstance(resource_type, str)
            or resource_type not in rows
            or not isinstance(evaluation_state, str)
            or not isinstance(finding_count, int)
            or not isinstance(unsupported_count, int)
            or not isinstance(error_count, int)
            or not isinstance(error_codes, list)
            or any(not isinstance(code, str) for code in error_codes)
            or not isinstance(publication_counts, Mapping)
        ):
            raise ValueError("analyzer coverage resource row is malformed")
        row = rows[resource_type]
        observed_selected[resource_type] += 1
        if evaluation_state in {"evaluated_no_finding", "finding"}:
            _increment_coverage_count(row, "evaluated_count", 1)
        _increment_coverage_count(row, "finding_count", finding_count)
        _increment_coverage_count(row, "unsupported_count", unsupported_count)
        _increment_coverage_count(row, "error_count", error_count)
        row_error_codes = row["error_codes"]
        if not isinstance(row_error_codes, list):
            raise ValueError("analyzer coverage error codes are malformed")
        row["error_codes"] = sorted(set(row_error_codes) | set(error_codes))
        row_publications = row["publication_counts"]
        if not isinstance(row_publications, dict):
            raise ValueError("analyzer coverage publication counts are malformed")
        for state in _PUBLICATION_STATES:
            value = publication_counts.get(state)
            current = row_publications.get(state)
            if not isinstance(value, int) or not isinstance(current, int):
                raise ValueError("analyzer coverage publication count is malformed")
            row_publications[state] = current + value
    for resolution in resolutions:
        if observed_selected[resolution.resource_type] != resolution.selected_count:
            raise ValueError("analyzer coverage selected totals MUST reconcile")
    return [rows[resource_type] for resource_type in sorted(rows)]


def _increment_coverage_count(
    row: dict[str, object],
    key: str,
    increment: int,
) -> None:
    current = row.get(key)
    if not isinstance(current, int):
        raise ValueError("analyzer coverage count is malformed")
    row[key] = current + increment


async def run_once() -> AnalyzerJobReport:
    """Compose the tick from the environment and run one analyzer pass."""
    configured = parse_targets(os.environ.get(TARGETS_ENV, ""))
    trace_topologies = parse_trace_topologies(os.environ.get(TRACE_TOPOLOGIES_ENV, ""))
    window_seconds = parse_window_seconds(os.environ.get(WINDOW_ENV, ""))
    trace_window_seconds = resolve_trace_window_seconds(os.environ, window_seconds)
    trace_lookback_seconds = resolve_trace_lookback_seconds(
        os.environ,
        trace_window_seconds,
    )
    max_discovered = parse_max_discovered(os.environ.get(MAX_DISCOVERED_ENV, ""))

    inventory = build_inventory_sources()
    decision_evidence = build_decision_evidence_admission_provider()
    try:
        resolution = await resolve_analyzer_targets(
            configured=configured,
            store=inventory.projection if inventory is not None else None,
            now=datetime.now(tz=UTC),
            max_discovered=max_discovered,
            decision_evidence=decision_evidence,
            provider_references=(inventory.provider_references if inventory is not None else None),
            discovered_hold_reasons=discovered_telemetry_holds(
                monitor_workspace_id=_optional("FDAI_MONITOR_WORKSPACE_ID")
            ),
        )
    finally:
        close = getattr(decision_evidence, "aclose", None)
        if callable(close):
            await close()
    _LOGGER.info("analyzer_tick_targets_resolved", extra=resolution.to_dict())
    targets = resolution.targets
    if not targets and not trace_topologies:
        _LOGGER.info("analyzer_tick_no_targets")
        report = AnalyzerJobReport(
            analyzer=AnalyzerTickReport(targets=0, findings=0, published=0),
            trace_continuity=_empty_trace_report(),
            target_resolution=resolution,
        )
        return report

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
            # Azure Managed Prometheus exposes a cluster alias, not the exact
            # ARM identity required by inventory-backed analyzer queries.
            prometheus_base_url=None,
            prometheus_queries=None,
            prometheus_audience=None,
        )
        bus = _build_finding_bus(
            identity=identity,
            bootstrap_servers=bootstrap_servers,
            venue=venue,
        )
        try:
            if targets:
                analyzer_report = await AnalyzerTickRunner(
                    coordinator=build_analyzer_coordinator(
                        container.metric_provider,
                        targets=targets,
                    ),
                    event_bus=bus,
                    publication_ledger=build_publication_ledger(),
                    receipt_store=build_receipt_store(),
                    window_seconds=window_seconds,
                    publication_window_seconds=DEFAULT_PUBLICATION_WINDOW_SECONDS,
                    topic=topic,
                ).run_once(targets)
                await build_lifecycle_recorder().record_report(
                    analyzer_report,
                    at=datetime.now(tz=UTC),
                )
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
                    lookback_seconds=trace_lookback_seconds,
                    topic=topic,
                ).run_once(trace_topologies)
            else:
                trace_report = _empty_trace_report()
            report = AnalyzerJobReport(
                analyzer=analyzer_report,
                trace_continuity=trace_report,
                target_resolution=resolution,
            )
            return report
        finally:
            await bus.close()


async def _record_run_receipt(
    report: AnalyzerJobReport,
    *,
    scheduling: str,
    tick_id: str,
) -> None:
    await record_analyzer_run_receipt(
        environment=os.environ,
        tick_id=tick_id,
        recorded_at=datetime.now(tz=UTC),
        report=_report_body(report, scheduling=scheduling),
    )


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
    tick_timeout_seconds: float = DEFAULT_TICK_BUDGET_SECONDS,
    tick: Callable[[], Awaitable[AnalyzerJobReport]] = run_once,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Run fixed-rate serial ticks and keep retryable failures unready."""

    if not 1 <= interval_seconds <= 86_400:
        raise ValueError("analyzer loop interval_seconds MUST be in [1, 86400]")
    if max_ticks is not None and max_ticks < 1:
        raise ValueError("analyzer loop max_ticks MUST be positive")
    if not 0 < tick_timeout_seconds <= DEFAULT_TICK_BUDGET_SECONDS:
        raise ValueError("analyzer loop tick_timeout_seconds is out of bounds")
    completed = 0
    while max_ticks is None or completed < max_ticks:
        tick_started = monotonic()
        failure_reason: str | None = None
        try:
            report = await asyncio.wait_for(tick(), timeout=tick_timeout_seconds)
            await _record_run_receipt(
                report,
                scheduling="local_loop",
                tick_id=str(completed),
            )
        except TimeoutError:
            failure_reason = "tick_deadline"
        except AnalyzerTargetResolutionError:
            failure_reason = "target_resolution_unavailable"
        except AnalyzerRunReceiptPersistenceError:
            failure_reason = "run_receipt_unavailable"
        completed += 1
        if failure_reason is not None:
            if max_ticks is not None and completed >= max_ticks:
                print(
                    f"service=local-analyzer event=failed reason={failure_reason}",
                    flush=True,
                )
                return 1
            print(
                f"service=local-analyzer event=waiting reason={failure_reason}",
                flush=True,
            )
        else:
            _emit_report(report, scheduling="local_loop")
            if report.failed:
                if max_ticks is not None and completed >= max_ticks:
                    print("service=local-analyzer event=failed", flush=True)
                    return 1
                print("service=local-analyzer event=waiting reason=tick_failed", flush=True)
            else:
                print("service=local-analyzer event=ready", flush=True)
            if max_ticks is not None and completed >= max_ticks:
                return 0
        elapsed = monotonic() - tick_started
        next_interval = (
            min(float(interval_seconds), _TARGET_RESOLUTION_RETRY_SECONDS)
            if failure_reason == "target_resolution_unavailable"
            else float(interval_seconds)
        )
        await sleep(max(0.0, next_interval - elapsed))
    return 0


def _emit_report(report: AnalyzerJobReport, *, scheduling: str) -> None:
    summary = _report_body(report, scheduling=scheduling)
    _LOGGER.info("analyzer_tick_complete", extra=summary)
    print(json.dumps(summary, sort_keys=True), flush=True)


def _report_body(report: AnalyzerJobReport, *, scheduling: str) -> dict[str, Any]:
    """Build the one report body shared by persistence, logs, and stdout."""

    return report.to_dict(
        scheduling=scheduling,
        metric_delays=metric_source_delays(os.environ),
    )


async def _run_once_with_receipt(*, timeout_seconds: float, scheduling: str) -> AnalyzerJobReport:
    report = await asyncio.wait_for(run_once(), timeout=timeout_seconds)
    await _record_run_receipt(report, scheduling=scheduling, tick_id="0")
    return report


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
        scheduling = resolve_scheduling_mode(os.environ.get("FDAI_ANALYZER_SCHEDULING_MODE", ""))
        report = asyncio.run(
            _run_once_with_receipt(
                timeout_seconds=tick_budget,
                scheduling=scheduling,
            )
        )
    except KeyboardInterrupt:
        return 130
    _emit_report(
        report,
        scheduling=scheduling,
    )
    return 1 if report.failed else 0


__all__ = [
    "BUDGET_ENV",
    "DEFAULT_MAX_DISCOVERED",
    "DEFAULT_TRACE_LOOKBACK_SECONDS",
    "INGRESS_TOPIC_ENV",
    "INVENTORY_DSN_ENV",
    "LOOP_INTERVAL_ENV",
    "MAX_DISCOVERED_ENV",
    "POD_EVIDENCE_JSON_ENV",
    "STATE_STORE_DSN_ENV",
    "StateStoreAnalyzerReceiptStore",
    "TARGETS_ENV",
    "TOPIC_ENV",
    "TRACE_LOOKBACK_ENV",
    "TRACE_TOPOLOGIES_ENV",
    "TRACE_WINDOW_ENV",
    "WINDOW_ENV",
    "AnalyzerJobReport",
    "build_analyzer_coordinator",
    "build_decision_evidence_admission_provider",
    "build_inventory_sources",
    "build_lifecycle_recorder",
    "build_publication_ledger",
    "build_receipt_store",
    "main",
    "metric_source_delays",
    "parse_loop_interval",
    "parse_max_discovered",
    "parse_targets",
    "parse_tick_budget",
    "parse_trace_topologies",
    "parse_window_seconds",
    "resolve_finding_topic",
    "resolve_scheduling_mode",
    "resolve_trace_lookback_seconds",
    "resolve_trace_window_seconds",
    "run_loop",
    "run_once",
]


if __name__ == "__main__":
    sys.exit(main())
