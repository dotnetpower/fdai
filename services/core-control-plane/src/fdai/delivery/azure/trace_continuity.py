"""Bounded Log Analytics source for distributed-trace continuity observations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.detection.trace_continuity import (
    TraceSpanObservation,
    TraceTopologyObservation,
)
from fdai.shared.providers.observation import LogQueryProvider

_MAX_TARGETS = 32
_MAX_ROWS = 2_000

TRACE_CONTINUITY_KQL = """
union isfuzzy=true
    (AppRequests
    | project TimeGenerated, OperationId, Id, Properties),
    (AppDependencies
    | project TimeGenerated, OperationId, Id, Properties)
| extend
    topology_ref = tostring(Properties["fdai.trace.topology_ref"]),
    scenario_id = tostring(Properties["fdai.trace.scenario_id"]),
    hop = tostring(Properties["fdai.trace.hop"]),
    sequence = toint(Properties["fdai.trace.sequence"]),
    completed = tobool(Properties["fdai.trace.completed"])
| where isnotempty(topology_ref) and isnotempty(scenario_id) and isnotempty(hop)
| project
    topology_ref,
    scenario_id,
    trace_id = tostring(OperationId),
    span_id = tostring(Id),
    hop,
    sequence,
    observed_at = TimeGenerated,
    completed
| order by observed_at asc
""".strip()


class TraceContinuitySourceError(RuntimeError):
    """Signal unavailable, truncated, or malformed continuity evidence."""


@dataclass(frozen=True, slots=True)
class TraceTopologyTarget:
    """Deployment-supplied expected topology without credentials or tenant values."""

    topology_ref: str
    resource_ref: str
    expected_hops: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.topology_ref or len(self.topology_ref) > 512:
            raise ValueError("TraceTopologyTarget.topology_ref MUST be bounded non-empty text")
        if not self.resource_ref or len(self.resource_ref) > 512:
            raise ValueError("TraceTopologyTarget.resource_ref MUST be bounded non-empty text")
        if not 2 <= len(self.expected_hops) <= 32:
            raise ValueError("TraceTopologyTarget.expected_hops MUST contain 2 to 32 hops")
        if len(set(self.expected_hops)) != len(self.expected_hops):
            raise ValueError("TraceTopologyTarget.expected_hops MUST be unique")
        if any(not hop or len(hop) > 128 for hop in self.expected_hops):
            raise ValueError("TraceTopologyTarget.expected_hops MUST be bounded text")


class AzureTraceContinuitySource:
    """Read one bounded workspace query and normalize configured topology runs."""

    def __init__(
        self,
        provider: LogQueryProvider,
        *,
        max_rows: int = _MAX_ROWS,
    ) -> None:
        if not 1 <= max_rows <= _MAX_ROWS:
            raise ValueError(f"trace continuity max_rows MUST be in [1, {_MAX_ROWS}]")
        self._provider = provider
        self._max_rows = max_rows

    async def collect(
        self,
        targets: Sequence[TraceTopologyTarget],
        *,
        window_seconds: int,
        window_bucket: str,
    ) -> tuple[TraceTopologyObservation, ...]:
        """Collect configured runs; partial or malformed evidence fails closed."""
        if not 1 <= len(targets) <= _MAX_TARGETS:
            raise ValueError(f"trace continuity targets MUST contain 1 to {_MAX_TARGETS} items")
        if window_seconds < 1:
            raise ValueError("trace continuity window_seconds MUST be positive")
        if not window_bucket:
            raise ValueError("trace continuity window_bucket MUST be non-empty")
        target_by_ref = {target.topology_ref: target for target in targets}
        if len(target_by_ref) != len(targets):
            raise ValueError("trace continuity topology_ref values MUST be unique")

        result = await self._provider.query_log(
            query=TRACE_CONTINUITY_KQL,
            window=f"PT{window_seconds}S",
            max_rows=self._max_rows,
        )
        if result.truncated:
            raise TraceContinuitySourceError("trace continuity evidence was truncated")

        grouped: dict[tuple[str, str], list[TraceSpanObservation]] = {}
        completed: dict[tuple[str, str], bool] = {}
        for row in result.rows:
            topology_ref = _required_text(row, "topology_ref")
            target = target_by_ref.get(topology_ref)
            if target is None:
                continue
            scenario_id = _required_text(row, "scenario_id")
            group_key = (topology_ref, scenario_id)
            span_id = _required_text(row, "span_id")
            grouped.setdefault(group_key, []).append(
                TraceSpanObservation(
                    trace_id=_required_text(row, "trace_id"),
                    span_id=span_id,
                    hop=_required_text(row, "hop"),
                    sequence=_required_int(row, "sequence"),
                    observed_at=_required_datetime(row, "observed_at"),
                    evidence_ref=f"appinsights:{span_id}",
                )
            )
            completed[group_key] = completed.get(group_key, False) or _required_bool(
                row,
                "completed",
            )

        observations: list[TraceTopologyObservation] = []
        for (topology_ref, scenario_id), spans in sorted(grouped.items()):
            target = target_by_ref[topology_ref]
            observations.append(
                TraceTopologyObservation(
                    topology_ref=topology_ref,
                    scenario_id=scenario_id,
                    resource_ref=target.resource_ref,
                    window_bucket=window_bucket,
                    expected_hops=target.expected_hops,
                    spans=tuple(spans),
                    completed=completed[(topology_ref, scenario_id)],
                )
            )
        return tuple(observations)


def _required_text(row: Any, field: str) -> str:
    value = row.get(field) if hasattr(row, "get") else None
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise TraceContinuitySourceError(
            f"trace continuity row {field} MUST be bounded non-empty text"
        )
    return value.strip()


def _required_int(row: Any, field: str) -> int:
    value = row.get(field) if hasattr(row, "get") else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TraceContinuitySourceError(
            f"trace continuity row {field} MUST be a non-negative integer"
        )
    return value


def _required_bool(row: Any, field: str) -> bool:
    value = row.get(field) if hasattr(row, "get") else None
    if not isinstance(value, bool):
        raise TraceContinuitySourceError(f"trace continuity row {field} MUST be boolean")
    return value


def _required_datetime(row: Any, field: str) -> datetime:
    value = row.get(field) if hasattr(row, "get") else None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TraceContinuitySourceError(
                f"trace continuity row {field} MUST be RFC 3339"
            ) from exc
    else:
        raise TraceContinuitySourceError(f"trace continuity row {field} MUST be RFC 3339")
    if parsed.tzinfo is None:
        raise TraceContinuitySourceError(f"trace continuity row {field} MUST be timezone-aware")
    return parsed


__all__ = [
    "TRACE_CONTINUITY_KQL",
    "AzureTraceContinuitySource",
    "TraceContinuitySourceError",
    "TraceTopologyTarget",
]
