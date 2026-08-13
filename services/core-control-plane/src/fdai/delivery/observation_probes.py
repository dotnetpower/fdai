"""Adapt existing provider-neutral read seams to observation campaign probes."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from fdai.delivery.observation_campaign import (
    ObservationCoverage,
    ObservationProbeContractError,
    ObservationProbeResult,
    ObservationSourceSpec,
)
from fdai.shared.providers.inventory import Inventory
from fdai.shared.providers.log_query import LogQuery, LogQueryProvider
from fdai.shared.providers.metric import MetricProvider, MetricQuery
from fdai.shared.providers.read_investigation import (
    EvidenceLimitationKind,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadInvestigationProvider,
    ReadToolId,
    ReadToolLimits,
    ResolvedResource,
)

TargetSupplier = Callable[[int], Awaitable[Sequence[ResolvedResource]]]


class InventoryDeltaObservationProbe:
    """Read every bounded delta batch and return its terminal cursor."""

    def __init__(self, inventory: Inventory, *, initial_cursor: str = "initial") -> None:
        if not initial_cursor:
            raise ValueError("initial inventory cursor MUST be non-empty")
        self._inventory = inventory
        self._initial_cursor = initial_cursor

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        evidence_count = 0
        next_cursor = cursor or self._initial_cursor
        final = False
        async for batch in self._inventory.delta(next_cursor):
            evidence_count += len(batch.resources) + len(batch.links)
            if evidence_count > spec.max_results:
                return ObservationProbeResult(
                    coverage=ObservationCoverage.PARTIAL,
                    evidence_count=spec.max_results,
                    cursor=next_cursor,
                    reason_codes=("result_limit",),
                )
            if batch.cursor is not None:
                next_cursor = batch.cursor
            final = final or batch.final
        if not final:
            return ObservationProbeResult(
                coverage=ObservationCoverage.PARTIAL,
                evidence_count=evidence_count,
                cursor=cursor,
                reason_codes=("incomplete_delta",),
            )
        return ObservationProbeResult(
            coverage=ObservationCoverage.READY,
            evidence_count=evidence_count,
            cursor=next_cursor,
        )


class LogQueryObservationProbe:
    """Run one server-owned log expression inside source limits."""

    def __init__(
        self,
        provider: LogQueryProvider,
        *,
        expression: str,
        labels: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not expression.strip() or len(expression) > 16_000:
            raise ValueError("observation log expression MUST be bounded non-empty text")
        self._provider = provider
        self._expression = expression
        self._labels = dict(labels or {})
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        del cursor
        until = self._clock()
        count = 0
        observed_bytes = 0
        async for record in self._provider.query(
            LogQuery(
                expression=self._expression,
                labels=self._labels,
                since=until - timedelta(seconds=spec.lookback_seconds),
                until=until,
                limit=spec.max_results,
            )
        ):
            count += 1
            observed_bytes += len(record.body.encode("utf-8"))
            if observed_bytes > spec.max_output_bytes:
                return ObservationProbeResult(
                    coverage=ObservationCoverage.PARTIAL,
                    evidence_count=count,
                    reason_codes=("byte_limit",),
                )
        return ObservationProbeResult(
            coverage=ObservationCoverage.READY,
            evidence_count=count,
        )


class MetricObservationProbe:
    """Read a reviewed metric set without retaining samples or labels."""

    def __init__(
        self,
        provider: MetricProvider,
        *,
        metric_names: Sequence[str],
        labels: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        names = tuple(dict.fromkeys(name.strip() for name in metric_names if name.strip()))
        if not names or len(names) > 64 or any(len(name) > 128 for name in names):
            raise ValueError("observation metric names MUST contain 1 to 64 bounded values")
        self._provider = provider
        self._metric_names = names
        self._labels = dict(labels or {})
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        del cursor
        until = self._clock()
        count = 0
        observed_bytes = 0
        for metric_name in self._metric_names:
            async for point in self._provider.query(
                MetricQuery(
                    metric_name=metric_name,
                    labels=self._labels,
                    since=until - timedelta(seconds=spec.lookback_seconds),
                    until=until,
                )
            ):
                count += 1
                try:
                    observed_bytes += len(
                        json.dumps(
                            {
                                "metric_name": point.metric_name,
                                "at": point.at.isoformat(),
                                "value": point.value,
                                "labels": dict(point.labels),
                            },
                            allow_nan=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    )
                except (TypeError, ValueError) as exc:
                    raise ObservationProbeContractError(
                        "metric provider returned invalid point metadata"
                    ) from exc
                if observed_bytes > spec.max_output_bytes:
                    return ObservationProbeResult(
                        coverage=ObservationCoverage.PARTIAL,
                        evidence_count=count,
                        reason_codes=("byte_limit",),
                    )
                if count >= spec.max_results:
                    return ObservationProbeResult(
                        coverage=ObservationCoverage.PARTIAL,
                        evidence_count=count,
                        reason_codes=("result_limit",),
                    )
        return ObservationProbeResult(
            coverage=ObservationCoverage.READY,
            evidence_count=count,
        )


class ReadInvestigationObservationProbe:
    """Run reviewed evidence tools across a bounded promoted-inventory target set."""

    def __init__(
        self,
        provider: ReadInvestigationProvider,
        *,
        target_supplier: TargetSupplier,
        tools: Sequence[ReadToolId],
    ) -> None:
        selected = tuple(dict.fromkeys(tools))
        supported = {
            ReadToolId.QUERY_RESOURCE_ACTIVITY,
            ReadToolId.QUERY_RESOURCE_HEALTH,
            ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
            ReadToolId.QUERY_NETWORK_SECURITY,
            ReadToolId.QUERY_NETWORK_PEERINGS,
        }
        if not selected or set(selected) - supported:
            raise ValueError("observation read tools MUST be supported evidence reads")
        self._provider = provider
        self._target_supplier = target_supplier
        self._tools = selected

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        del cursor
        targets = tuple(await self._target_supplier(spec.max_targets))
        if len(targets) > spec.max_targets:
            raise ObservationProbeContractError("observation target supplier exceeded max_targets")
        limits = ReadToolLimits(
            timeout_seconds=min(spec.timeout_seconds, 120),
            max_results=min(spec.max_results, 200),
            max_output_bytes=min(max(spec.max_output_bytes, 1_024), 1_000_000),
        )
        attempts: list[ReadEvidenceAttempt] = []
        for target in targets:
            for tool in self._tools:
                attempts.append(
                    await _read(
                        self._provider,
                        tool,
                        target,
                        lookback_seconds=spec.lookback_seconds,
                        limits=limits,
                    )
                )
        return _summarize_attempts(attempts, max_results=spec.max_results)


async def _read(
    provider: ReadInvestigationProvider,
    tool: ReadToolId,
    resource: ResolvedResource,
    *,
    lookback_seconds: int,
    limits: ReadToolLimits,
) -> ReadEvidenceAttempt:
    if tool is ReadToolId.QUERY_RESOURCE_ACTIVITY:
        return await provider.query_resource_activity(
            resource,
            lookback_seconds=lookback_seconds,
            limits=limits,
        )
    if tool is ReadToolId.QUERY_RESOURCE_HEALTH:
        return await provider.query_resource_health(
            resource,
            lookback_seconds=lookback_seconds,
            limits=limits,
        )
    if tool is ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS:
        return await provider.query_guest_shutdown_events(
            resource,
            lookback_seconds=lookback_seconds,
            limits=limits,
        )
    if tool is ReadToolId.QUERY_NETWORK_SECURITY:
        return await provider.query_network_security(resource, limits=limits)
    return await provider.query_network_peerings(resource, limits=limits)


def _summarize_attempts(
    attempts: Sequence[ReadEvidenceAttempt],
    *,
    max_results: int,
) -> ObservationProbeResult:
    if not attempts:
        return ObservationProbeResult(coverage=ObservationCoverage.READY)
    evidence_count = sum(len(attempt.evidence.records) for attempt in attempts)
    limitations = {
        limitation for attempt in attempts for limitation in attempt.evidence.limitations
    }
    unavailable = sum(attempt.evidence.status is EvidenceStatus.UNAVAILABLE for attempt in attempts)
    if evidence_count > max_results:
        return ObservationProbeResult(
            coverage=ObservationCoverage.PARTIAL,
            evidence_count=max_results,
            reason_codes=("result_limit",),
        )
    if unavailable == 0:
        return ObservationProbeResult(
            coverage=ObservationCoverage.READY,
            evidence_count=evidence_count,
        )
    reason_codes = tuple(sorted(limitation.value for limitation in limitations)) or (
        "source_unavailable",
    )
    if unavailable < len(attempts):
        coverage = ObservationCoverage.PARTIAL
    elif EvidenceLimitationKind.UNAUTHORIZED in limitations:
        coverage = ObservationCoverage.UNAUTHORIZED
    elif EvidenceLimitationKind.RETENTION_BOUNDARY in limitations:
        coverage = ObservationCoverage.RETENTION_GAP
    else:
        coverage = ObservationCoverage.UNCONFIGURED
    return ObservationProbeResult(
        coverage=coverage,
        evidence_count=evidence_count,
        reason_codes=reason_codes,
    )


__all__ = [
    "InventoryDeltaObservationProbe",
    "LogQueryObservationProbe",
    "MetricObservationProbe",
    "ReadInvestigationObservationProbe",
    "TargetSupplier",
]
