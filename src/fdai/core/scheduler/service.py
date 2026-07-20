"""Scheduler service - fires due tasks as synthetic control-loop events.

Mirrors :class:`~fdai.core.slo.runner.SloBurnRunner`: a periodic
``run_once`` cycle driven by an out-of-band trigger (a Container Apps Job /
cron in production). Each due :class:`ScheduledTask` is turned into an
:class:`Event` and published to the event-ingest topic, so the standard
trust-router + risk-gate path governs any resulting action. The scheduler
itself is deterministic-first and never executes a change.

``compute_due`` is a pure, I/O-free function so "which tasks fire at time
T" is exhaustively testable without real time or a broker.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from croniter import croniter

from fdai.core.scheduler.isolation import isolation_payload
from fdai.core.scheduler.models import ScheduledTask, ScheduleKind
from fdai.core.scheduler.run_ledger import (
    InMemoryScheduleRunLedger,
    ScheduleDispatchRun,
    ScheduleDispatchStatus,
    ScheduleRunLedger,
)
from fdai.core.scheduler.store import ScheduleStore
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.telemetry.transitions import (
    RoutingTransition,
    RoutingTransitionSink,
    default_transition_emitter,
    emit_transition_safely,
)

_LOGGER = logging.getLogger(__name__)

SCHEDULE_EVENT_TOPIC = "aw.schedule.events"
_SOURCE = "fdai.core.scheduler"


def compute_due(tasks: Sequence[ScheduledTask], *, now: datetime) -> list[ScheduledTask]:
    """Return the subset of ``tasks`` that are due to fire at ``now``.

    A task is due when it is enabled, its ``start_at`` (if any) has passed,
    and either it has never run or at least ``interval_seconds`` have
    elapsed since ``last_run``. Pure and deterministic.
    """
    due: list[ScheduledTask] = []
    for task in tasks:
        if not task.enabled:
            continue
        if task.start_at is not None and now < task.start_at:
            continue
        if task.kind is ScheduleKind.EVENT_EXIT and task.exit_observed_at is not None:
            continue
        if task.kind is ScheduleKind.ONE_SHOT:
            if task.last_run is None:
                due.append(task)
            continue
        if task.kind is ScheduleKind.CRON:
            local_now = now.astimezone(ZoneInfo(task.timezone))
            if not croniter.match(task.cron_expression or "", local_now):
                continue
            if task.last_run is not None and _minute_bucket(task.last_run) == _minute_bucket(now):
                continue
            due.append(task)
            continue
        if task.last_run is None:
            due.append(task)
            continue
        elapsed = (now - task.last_run).total_seconds()
        if elapsed >= task.interval_seconds:
            due.append(task)
    return due


def _schedule_idempotency_key(task: ScheduledTask, now: datetime) -> str:
    """Stable key per interval bucket so a retried tick does not double-fire."""
    if task.kind is ScheduleKind.ONE_SHOT:
        bucket = f"at:{int((task.start_at or now).timestamp())}"
    elif task.kind is ScheduleKind.CRON:
        bucket = f"cron:{_minute_bucket(now)}"
    else:
        bucket = f"interval:{int(now.timestamp() // task.interval_seconds)}"
    return f"schedule:{task.task_id}:{bucket}"


def _minute_bucket(value: datetime) -> int:
    return int(value.timestamp() // 60)


@dataclass(frozen=True, slots=True)
class SchedulerRunReport:
    """Outcome of one ``run_once`` cycle."""

    fired: int
    publish_errors: tuple[tuple[str, str], ...] = ()
    """``(task_id, short_error)`` for each publish that failed."""
    duplicates_suppressed: int = 0


class SchedulerService:
    """Fire due scheduled tasks into the control loop."""

    __slots__ = (
        "_bus",
        "_clock",
        "_ledger",
        "_mode",
        "_store",
        "_topic",
        "_transition_sink",
    )

    def __init__(
        self,
        *,
        store: ScheduleStore,
        event_bus: EventBus,
        clock: Callable[[], datetime] | None = None,
        topic: str = SCHEDULE_EVENT_TOPIC,
        mode: Mode = Mode.SHADOW,
        run_ledger: ScheduleRunLedger | None = None,
        transition_sink: RoutingTransitionSink | None = None,
    ) -> None:
        self._store = store
        self._bus = event_bus
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        self._topic = topic
        self._mode = mode
        self._ledger = run_ledger or InMemoryScheduleRunLedger()
        self._transition_sink = transition_sink or default_transition_emitter()

    async def run_once(self, *, now: datetime | None = None) -> SchedulerRunReport:
        at = now or self._clock()
        tasks = await self._store.list_all()
        due = compute_due(tasks, now=at)

        return await self._dispatch(due, at=at)

    async def run_task_now(
        self,
        task_id: str,
        *,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> SchedulerRunReport:
        """Dispatch one enabled task immediately with caller-stable idempotency."""

        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise ValueError("run-now idempotency_key MUST be non-empty and bounded")
        task = await self._store.get(task_id)
        if not task.enabled:
            raise ValueError("cannot run a disabled scheduled task")
        at = now or self._clock()
        return await self._dispatch(
            (task,),
            at=at,
            manual_idempotency_key=idempotency_key.strip(),
        )

    async def _dispatch(
        self,
        tasks: Sequence[ScheduledTask],
        *,
        at: datetime,
        manual_idempotency_key: str | None = None,
    ) -> SchedulerRunReport:

        fired = 0
        duplicates_suppressed = 0
        publish_errors: list[tuple[str, str]] = []
        for task in tasks:
            key = task.resource_ref or task.task_id
            run_id = (
                f"schedule:{task.task_id}:manual:{manual_idempotency_key}"
                if manual_idempotency_key is not None
                else _schedule_idempotency_key(task, at)
            )
            claimed = await self._ledger.claim(
                ScheduleDispatchRun(
                    run_id=run_id,
                    task_id=task.task_id,
                    scheduled_for=at,
                    claimed_at=at,
                )
            )
            if not claimed:
                duplicates_suppressed += 1
                continue
            try:
                payload = self._build_payload(task, at)
                await self._bus.publish(self._topic, key, payload)
            except Exception as exc:  # noqa: BLE001 - one bad task must not silence the rest
                await self._ledger.complete(
                    run_id,
                    status=ScheduleDispatchStatus.FAILED,
                    at=at,
                    error_kind=type(exc).__name__,
                )
                publish_errors.append((task.task_id, f"{type(exc).__name__}:{exc}"))
                self._emit(task, "dispatch", "failed", {"error_kind": type(exc).__name__})
                _LOGGER.warning(
                    "schedule_publish_failed",
                    extra={"task_id": task.task_id, "error": str(exc)},
                )
                continue
            await self._ledger.complete(
                run_id,
                status=ScheduleDispatchStatus.PUBLISHED,
                at=at,
            )
            await self._store.mark_run(task.task_id, at)
            fired += 1
            self._emit(task, "dispatch", "accepted", {})

        return SchedulerRunReport(
            fired=fired,
            publish_errors=tuple(publish_errors),
            duplicates_suppressed=duplicates_suppressed,
        )

    async def observe_event(self, event: Event) -> int:
        """Disable event-exit schedules matching one normalized event type."""
        return await self._store.mark_exit_event(event.event_type, event.detected_at)

    def _emit(
        self,
        task: ScheduledTask,
        name: str,
        outcome: str,
        attributes: dict[str, str],
    ) -> None:
        emit_transition_safely(
            self._transition_sink,
            RoutingTransition(
                domain="scheduler",
                name=name,
                outcome=outcome,
                attributes={"schedule_kind": task.kind.value, **attributes},
            ),
        )

    def _build_event(self, task: ScheduledTask, at: datetime) -> Event:
        payload = {
            **dict(task.event_payload),
            "scheduled_task": {
                "task_id": task.task_id,
                "name": task.name,
                "created_by": task.created_by,
                "isolation": isolation_payload(task.isolation_profile),
            },
        }
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=_schedule_idempotency_key(task, at),
            source=_SOURCE,
            event_type=task.event_type,
            resource_ref=task.resource_ref,
            payload=payload,
            detected_at=at,
            ingested_at=at,
            incident_correlation=IncidentCorrelation.NONE,
            mode=self._mode,
        )

    def _build_payload(self, task: ScheduledTask, at: datetime) -> dict[str, object]:
        proposal = task.event_payload.get("action_proposal")
        if not isinstance(proposal, dict):
            return self._build_event(task, at).model_dump(mode="json")
        initiator = proposal.get("initiator_principal")
        action_type = proposal.get("action_type")
        params = proposal.get("params")
        if (
            not isinstance(initiator, str)
            or not initiator
            or not isinstance(action_type, str)
            or not action_type
            or not isinstance(params, dict)
        ):
            raise ValueError(f"scheduled task {task.task_id!r} has an invalid action_proposal")
        idempotency_key = _schedule_idempotency_key(task, at)
        return {
            "schema_version": "1.0.0",
            "idempotency_key": idempotency_key,
            "correlation_id": idempotency_key,
            "incident_correlation": IncidentCorrelation.NONE.value,
            "initiator_principal": initiator,
            "operator_initiated": True,
            "action_type": action_type,
            "resource_id": task.resource_ref,
            "event_type": "operator_request",
            "params": dict(params),
            "scheduled_task": {
                "task_id": task.task_id,
                "name": task.name,
                "created_by": task.created_by,
                "isolation": isolation_payload(task.isolation_profile),
            },
        }


__all__ = [
    "SCHEDULE_EVENT_TOPIC",
    "SchedulerRunReport",
    "SchedulerService",
    "compute_due",
]
