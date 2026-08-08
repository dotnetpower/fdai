"""Deterministic incident lifecycle metrics projected from append-only audit."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fdai.shared.contracts.models import IncidentSeverity, IncidentState


@dataclass(frozen=True, slots=True)
class IncidentLifecycleMetrics:
    """Bounded aggregate facts for KPI and notification surfaces."""

    created_total: int
    agent_created_total: int
    operator_created_total: int
    assignments_total: int
    tickets_linked_total: int
    reopen_total: int
    current_by_state: Mapping[str, int]
    current_by_severity: Mapping[str, int]
    mean_acknowledgement_seconds: float | None
    mean_resolution_seconds: float | None


@dataclass(slots=True)
class _Timeline:
    opened_at: datetime
    state: IncidentState
    severity: IncidentSeverity
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None


def project_incident_metrics(
    entries: Iterable[Mapping[str, Any]],
    *,
    agent_principals: Collection[str] = (),
) -> IncidentLifecycleMetrics:
    """Project deduplicated lifecycle rows into current and duration metrics."""
    agents = frozenset(agent_principals)
    seen_keys: set[str] = set()
    timelines: dict[UUID, _Timeline] = {}
    agent_created = 0
    operator_created = 0
    assignments = 0
    tickets = 0
    reopens = 0

    for entry in entries:
        key = _required_string(entry, "idempotency_key")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        kind = _required_string(entry, "kind")
        incident_id = UUID(_required_string(entry, "incident_id"))
        if kind == "incident.open":
            if incident_id in timelines:
                continue
            actor = _required_string(entry, "actor_oid")
            timelines[incident_id] = _Timeline(
                opened_at=_aware_datetime(entry, "opened_at"),
                state=IncidentState(_required_string(entry, "state")),
                severity=IncidentSeverity(_required_string(entry, "severity")),
            )
            if actor in agents:
                agent_created += 1
            else:
                operator_created += 1
            continue
        timeline = timelines.get(incident_id)
        if timeline is None:
            raise ValueError(f"incident metric row precedes open: {incident_id}")
        if kind == "incident.members":
            continue
        if kind == "incident.assigned":
            assignments += 1
            continue
        if kind == "incident.ticket":
            tickets += 1
            continue
        if kind != "incident.transition":
            raise ValueError(f"unsupported incident metric kind: {kind}")
        from_state = IncidentState(_required_string(entry, "from_state"))
        to_state = IncidentState(_required_string(entry, "to_state"))
        if timeline.state is not from_state:
            raise ValueError(f"incident metric state mismatch: {incident_id}")
        changed_at = _aware_datetime(entry, "at")
        if timeline.acknowledged_at is None and from_state is IncidentState.OPEN:
            timeline.acknowledged_at = changed_at
        if to_state is IncidentState.RESOLVED:
            timeline.resolved_at = changed_at
        if from_state is IncidentState.RESOLVED and to_state is IncidentState.TRIAGING:
            reopens += 1
            timeline.resolved_at = None
        severity_value = _optional_string(entry, "severity")
        if severity_value is not None:
            timeline.severity = IncidentSeverity(severity_value)
        timeline.state = to_state

    state_counts = Counter(timeline.state.value for timeline in timelines.values())
    severity_counts = Counter(timeline.severity.value for timeline in timelines.values())
    acknowledgement_durations = [
        (timeline.acknowledged_at - timeline.opened_at).total_seconds()
        for timeline in timelines.values()
        if timeline.acknowledged_at is not None
    ]
    resolution_durations = [
        (timeline.resolved_at - timeline.opened_at).total_seconds()
        for timeline in timelines.values()
        if timeline.resolved_at is not None
    ]
    return IncidentLifecycleMetrics(
        created_total=len(timelines),
        agent_created_total=agent_created,
        operator_created_total=operator_created,
        assignments_total=assignments,
        tickets_linked_total=tickets,
        reopen_total=reopens,
        current_by_state=dict(sorted(state_counts.items())),
        current_by_severity=dict(sorted(severity_counts.items())),
        mean_acknowledgement_seconds=_mean(acknowledgement_durations),
        mean_resolution_seconds=_mean(resolution_durations),
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _required_string(entry: Mapping[str, Any], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} MUST be a non-empty string")
    return value


def _optional_string(entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} MUST be a string or null")
    return value or None


def _aware_datetime(entry: Mapping[str, Any], key: str) -> datetime:
    value = datetime.fromisoformat(_required_string(entry, key))
    if value.tzinfo is None:
        raise ValueError(f"{key} MUST be timezone-aware")
    return value


__all__ = ["IncidentLifecycleMetrics", "project_incident_metrics"]
