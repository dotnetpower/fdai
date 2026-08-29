"""Azure Monitor implementation of the ceiling-lowering live blast probe."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.rule_catalog.schema.probe import ProbeManifest
from fdai.shared.providers.blast_probe import (
    BlastProbeConfigError,
    BlastProbeTimeoutError,
    ProbeQuery,
    ProbeResult,
    ProbeVerdict,
)
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)

_COMPARISON = re.compile(
    r"^(?P<field>[a-z][a-z0-9_]*)\s*(?P<operator><|>=)\s*(?P<value>\d+(?:\.\d+)?)$"
)


@dataclass(frozen=True, slots=True)
class AzureMonitorProbeDefinition:
    """One reviewed Azure Monitor metric and deterministic threshold mapping."""

    probe_id: str
    metric_name: str
    aggregation: str
    window_minutes: int
    timeout_seconds: float
    result_field: str
    quiet_below: float
    active_below: float

    def __post_init__(self) -> None:
        if not self.probe_id or not self.metric_name or not self.result_field:
            raise BlastProbeConfigError("Azure Monitor probe identifiers MUST be non-empty")
        if self.aggregation not in {"average", "total", "p95"}:
            raise BlastProbeConfigError("Azure Monitor probe aggregation is unsupported")
        if self.window_minutes < 1:
            raise BlastProbeConfigError("Azure Monitor probe window_minutes MUST be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise BlastProbeConfigError("Azure Monitor probe timeout_seconds MUST be positive")
        if not (
            math.isfinite(self.quiet_below)
            and math.isfinite(self.active_below)
            and self.quiet_below <= self.active_below
        ):
            raise BlastProbeConfigError("Azure Monitor probe thresholds are invalid")


class AzureMonitorBlastProbe:
    """Measure reviewed metrics without granting execution authority."""

    def __init__(
        self,
        *,
        metric_provider: MetricProvider,
        definitions: Iterable[AzureMonitorProbeDefinition],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        materialized = tuple(definitions)
        indexed = {definition.probe_id: definition for definition in materialized}
        if not indexed:
            raise BlastProbeConfigError("Azure Monitor probe definitions MUST be non-empty")
        if len(indexed) != len(materialized):
            raise BlastProbeConfigError("Azure Monitor probe ids MUST be unique")
        self._metric_provider = metric_provider
        self._definitions = indexed
        self._clock = clock

    async def measure(self, query: ProbeQuery) -> ProbeResult:
        """Return a fresh classification or a degraded active result on provider failure."""

        definition = self._definitions.get(query.probe_id)
        if definition is None:
            raise BlastProbeConfigError("Azure Monitor probe id is not configured")
        until = self._clock()
        if until.tzinfo is None or until.utcoffset() is None:
            raise BlastProbeConfigError("Azure Monitor probe clock MUST be timezone-aware")
        metric_query = MetricQuery(
            metric_name=definition.metric_name,
            labels={"resource_id": query.target_ref},
            since=until - timedelta(minutes=definition.window_minutes),
            until=until,
            aggregation=definition.aggregation,
        )
        try:
            async with asyncio.timeout(min(query.deadline_seconds, definition.timeout_seconds)):
                points = tuple([point async for point in self._metric_provider.query(metric_query)])
        except TimeoutError as exc:
            raise BlastProbeTimeoutError("Azure Monitor blast probe timed out") from exc
        except MetricProviderError:
            return ProbeResult(
                verdict=ProbeVerdict.ACTIVE,
                reason="Azure Monitor blast evidence is unavailable",
                degraded=True,
            )
        if not points:
            return ProbeResult(
                verdict=ProbeVerdict.ACTIVE,
                reason="Azure Monitor blast evidence is empty",
                degraded=True,
            )
        try:
            value = _aggregate(points, definition.aggregation)
        except MetricProviderError:
            return ProbeResult(
                verdict=ProbeVerdict.ACTIVE,
                reason="Azure Monitor blast evidence is invalid",
                degraded=True,
            )
        verdict = (
            ProbeVerdict.QUIET
            if value < definition.quiet_below
            else ProbeVerdict.ACTIVE
            if value < definition.active_below
            else ProbeVerdict.OVERLOADED
        )
        return ProbeResult(
            verdict=verdict,
            reason=f"Azure Monitor probe {query.probe_id} classified {verdict.value}",
            metrics={definition.result_field: value},
        )


def azure_monitor_probe_definitions(
    manifests: Iterable[ProbeManifest],
) -> tuple[AzureMonitorProbeDefinition, ...]:
    """Compile strict threshold definitions from reviewed probe manifests."""

    definitions = []
    for manifest in manifests:
        if manifest.adapter_ref != "probe-adapters/azure-monitor":
            continue
        payload = manifest.adapter_payload
        quiet = _comparison(manifest.interpretation.get("quiet"), expected_operator="<")
        active = _comparison(manifest.interpretation.get("active"), expected_operator="<")
        overloaded = _comparison(
            manifest.interpretation.get("overloaded"),
            expected_operator=">=",
        )
        if quiet[0] != active[0] or quiet[0] != overloaded[0]:
            raise BlastProbeConfigError("Azure Monitor probe result fields do not match")
        if active[1] != overloaded[1]:
            raise BlastProbeConfigError(
                "Azure Monitor active and overloaded thresholds do not meet"
            )
        definitions.append(
            AzureMonitorProbeDefinition(
                probe_id=manifest.id,
                metric_name=_required_text(payload, "metric_name"),
                aggregation=_required_text(payload, "aggregation").casefold(),
                window_minutes=_positive_int(payload, "window_minutes"),
                timeout_seconds=manifest.timeout_seconds,
                result_field=quiet[0],
                quiet_below=quiet[1],
                active_below=active[1],
            )
        )
    return tuple(definitions)


def _comparison(value: object, *, expected_operator: str) -> tuple[str, float]:
    if not isinstance(value, str) or (match := _COMPARISON.fullmatch(value.strip())) is None:
        raise BlastProbeConfigError("Azure Monitor probe interpretation is invalid")
    if match.group("operator") != expected_operator:
        raise BlastProbeConfigError("Azure Monitor probe comparison operator is invalid")
    return match.group("field"), float(match.group("value"))


def _required_text(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BlastProbeConfigError(f"Azure Monitor probe {key} MUST be non-empty")
    return value.strip()


def _positive_int(values: Mapping[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BlastProbeConfigError(f"Azure Monitor probe {key} MUST be positive")
    return value


def _aggregate(points: tuple[MetricPoint, ...], aggregation: str) -> float:
    values = sorted(point.value for point in points)
    if any(not math.isfinite(value) for value in values):
        raise MetricProviderError("Azure Monitor probe returned a non-finite metric")
    if aggregation == "total":
        return sum(values)
    if aggregation == "average":
        return sum(values) / len(values)
    index = max(0, math.ceil(len(values) * 0.95) - 1)
    return values[index]


__all__ = [
    "AzureMonitorBlastProbe",
    "AzureMonitorProbeDefinition",
    "azure_monitor_probe_definitions",
]
