"""Config-driven incident SLA evaluation and periodic escalation monitor."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from fdai.shared.contracts.models import IncidentSeverity, IncidentState

from .lifecycle import IncidentLifecycleNotice, IncidentLifecycleNotifier, IncidentNoticeKind

_LOG = logging.getLogger(__name__)
_MONITOR_ACTOR = "incident-sla-monitor"
_ACTIVE_STATES = frozenset({IncidentState.TRIAGING, IncidentState.MITIGATED})


@dataclass(frozen=True, slots=True)
class IncidentSlaPolicy:
    """Severity-specific acknowledgment and resolution deadlines."""

    acknowledge_seconds: Mapping[IncidentSeverity, int]
    resolve_seconds: Mapping[IncidentSeverity, int]

    def __post_init__(self) -> None:
        expected = frozenset(IncidentSeverity)
        if frozenset(self.acknowledge_seconds) != expected:
            raise ValueError("acknowledge_seconds MUST define sev1 through sev5")
        if frozenset(self.resolve_seconds) != expected:
            raise ValueError("resolve_seconds MUST define sev1 through sev5")
        if any(value < 1 for value in self.acknowledge_seconds.values()):
            raise ValueError("acknowledge_seconds values MUST be >= 1")
        if any(value < 1 for value in self.resolve_seconds.values()):
            raise ValueError("resolve_seconds values MUST be >= 1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> IncidentSlaPolicy:
        """Validate a JSON-shaped policy mapping at the config boundary."""
        acknowledge = _severity_seconds(value.get("acknowledge_seconds"), "acknowledge_seconds")
        resolve = _severity_seconds(value.get("resolve_seconds"), "resolve_seconds")
        return cls(acknowledge_seconds=acknowledge, resolve_seconds=resolve)

    def deadline_seconds(self, state: IncidentState, severity: IncidentSeverity) -> int | None:
        if state is IncidentState.OPEN:
            return self.acknowledge_seconds[severity]
        if state in _ACTIVE_STATES:
            return self.resolve_seconds[severity]
        return None


@dataclass(frozen=True, slots=True)
class _SlaIncident:
    incident_id: UUID
    state: IncidentState
    severity: IncidentSeverity
    entered_at: datetime


def evaluate_incident_sla(
    entries: Iterable[Mapping[str, Any]],
    *,
    policy: IncidentSlaPolicy,
    now: datetime,
) -> tuple[IncidentLifecycleNotice, ...]:
    """Return one stable breach notice per overdue current incident state."""
    if now.tzinfo is None:
        raise ValueError("incident SLA evaluation time MUST be timezone-aware")
    current: dict[UUID, _SlaIncident] = {}
    seen_keys: set[str] = set()
    for entry in entries:
        idempotency_key = _required_string(entry, "idempotency_key")
        if idempotency_key in seen_keys:
            continue
        seen_keys.add(idempotency_key)
        kind = _required_string(entry, "kind")
        if kind in {"incident.members", "incident.assigned", "incident.ticket"}:
            continue
        incident_id = UUID(_required_string(entry, "incident_id"))
        if kind == "incident.open":
            current[incident_id] = _SlaIncident(
                incident_id=incident_id,
                state=IncidentState(_required_string(entry, "state")),
                severity=IncidentSeverity(_required_string(entry, "severity")),
                entered_at=_aware_datetime(entry, "opened_at"),
            )
            continue
        if kind != "incident.transition":
            raise ValueError(f"unsupported incident SLA audit kind: {kind}")
        previous = current.get(incident_id)
        if previous is None:
            raise ValueError(f"incident SLA transition precedes open: {incident_id}")
        from_state = IncidentState(_required_string(entry, "from_state"))
        if previous.state is not from_state:
            raise ValueError(f"incident SLA state mismatch: {incident_id}")
        severity_value = _optional_string(entry, "severity")
        current[incident_id] = _SlaIncident(
            incident_id=incident_id,
            state=IncidentState(_required_string(entry, "to_state")),
            severity=(
                IncidentSeverity(severity_value)
                if severity_value is not None
                else previous.severity
            ),
            entered_at=_aware_datetime(entry, "at"),
        )

    notices: list[IncidentLifecycleNotice] = []
    for incident in sorted(current.values(), key=lambda item: str(item.incident_id)):
        seconds = policy.deadline_seconds(incident.state, incident.severity)
        if seconds is None:
            continue
        deadline = incident.entered_at + timedelta(seconds=seconds)
        if now < deadline:
            continue
        reason = (
            "acknowledgement_deadline_exceeded"
            if incident.state is IncidentState.OPEN
            else "resolution_deadline_exceeded"
        )
        notices.append(
            IncidentLifecycleNotice(
                kind=IncidentNoticeKind.SLA_BREACH,
                actor_oid=_MONITOR_ACTOR,
                occurred_at=deadline,
                incident_id=incident.incident_id,
                incident_state=incident.state,
                incident_severity=incident.severity,
                reason=reason,
            )
        )
    return tuple(notices)


class IncidentTransitionSource(Protocol):
    async def read_incident_transitions(self) -> tuple[Mapping[str, Any], ...]: ...


class IncidentSlaMonitor:
    """Periodically evaluate lifecycle audit and send durable breach notices."""

    def __init__(
        self,
        *,
        source: IncidentTransitionSource,
        notifier: IncidentLifecycleNotifier,
        policy: IncidentSlaPolicy,
        interval_seconds: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("incident SLA monitor interval_seconds MUST be positive")
        self._source = source
        self._notifier = notifier
        self._policy = policy
        self._interval_seconds = interval_seconds
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def scan_once(self) -> int:
        entries = await self._source.read_incident_transitions()
        notices = evaluate_incident_sla(entries, policy=self._policy, now=self._clock())
        for notice in notices:
            await self._notifier.notify(notice)
        return len(notices)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        await self.scan_once()
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="incident-sla-monitor")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is None:
            return
        await task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                try:
                    await self.scan_once()
                except Exception:  # noqa: BLE001 - next interval retries durable audit
                    _LOG.exception("incident_sla_scan_failed")


def _severity_seconds(value: object, field: str) -> dict[IncidentSeverity, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} MUST be a mapping")
    parsed: dict[IncidentSeverity, int] = {}
    for severity in IncidentSeverity:
        raw = value.get(severity.value)
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise ValueError(f"{field}.{severity.value} MUST be an integer")
        parsed[severity] = raw
    if set(value) != {severity.value for severity in IncidentSeverity}:
        raise ValueError(f"{field} MUST contain only sev1 through sev5")
    return parsed


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


__all__ = [
    "IncidentSlaMonitor",
    "IncidentSlaPolicy",
    "IncidentTransitionSource",
    "evaluate_incident_sla",
]
