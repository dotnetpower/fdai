"""Chat-based creation commands (SRE-agent slides 15-16).

Two async, RBAC-gated commands that let an operator create records from the
conversational surface, on top of the existing async writers:

- :class:`CreateIncidentCommand` - open an incident record via the
  :class:`~fdai.core.incident.registry.IncidentRegistry` (slide 15). The
  incident is the anchor a Saga handoff turns into a GitHub issue; this
  command creates the record, it does not execute a change.
- :class:`CreateScheduledTaskCommand` - create a recurring monitoring task
  in the shared :class:`~fdai.core.scheduler.store.ScheduleStore` (slide
  16), which the next scheduler tick fires into the control loop.

Both enforce a ``CONTRIBUTOR`` role floor. Neither is an autonomous action:
an incident is a record, and a scheduled task only re-emits a synthetic
event that the trust-router + risk-gate still govern (SchedulerService
defaults to shadow mode).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID, uuid4

from fdai.core.conversation.session import (
    Principal,
    Role,
    principal_has_role_at_least,
)
from fdai.core.incident.lifecycle import IncidentConfirmationError
from fdai.core.incident.registry import IncidentRegistry
from fdai.core.incident.workflow import IncidentLifecycleWorkflow
from fdai.core.scheduler.models import (
    ScheduledRunIsolationProfile,
    ScheduledTask,
    ScheduleKind,
)
from fdai.core.scheduler.store import ScheduleNotFoundError, ScheduleStore
from fdai.shared.contracts.models import Incident, IncidentSeverity
from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledResultOrigin,
)

_CREATE_FLOOR: Role = Role.CONTRIBUTOR


class CreationForbiddenError(PermissionError):
    """Raised when the principal is below the creation role floor."""


def _require_floor(principal: Principal, action: str) -> None:
    if not principal_has_role_at_least(principal.role, _CREATE_FLOOR):
        raise CreationForbiddenError(
            f"{action} requires role>={_CREATE_FLOOR.value}; principal role={principal.role.value}"
        )


class CreateIncidentCommand:
    """Open an incident from the conversational surface (slide 15)."""

    __slots__ = ("_workflow",)

    def __init__(
        self,
        *,
        registry: IncidentRegistry,
        workflow: IncidentLifecycleWorkflow | None = None,
    ) -> None:
        self._workflow = workflow or IncidentLifecycleWorkflow(registry=registry)

    async def create(
        self,
        *,
        principal: Principal,
        correlation_keys: Iterable[str],
        severity: IncidentSeverity,
        member_event_ids: Iterable[UUID] = (),
        confirmed: bool = False,
    ) -> Incident:
        """Open a confirmed structured incident request.

        Idempotent by correlation-key set - re-running with the same keys
        returns the same deterministic incident, never a duplicate.
        """
        _require_floor(principal, "create_incident")
        if not confirmed:
            raise IncidentConfirmationError("explicit incident creation confirmation is required")
        result = await self._workflow.open_confirmed_operator(
            principal=principal,
            correlation_keys=tuple(correlation_keys),
            severity=severity,
            member_event_ids=tuple(member_event_ids),
        )
        return result.incident


class CreateScheduledTaskCommand:
    """Create a recurring monitoring task from chat (slide 16)."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ScheduleStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        principal: Principal,
        name: str,
        interval_seconds: float,
        event_type: str,
        resource_ref: str | None = None,
        event_payload: Mapping[str, object] | None = None,
        task_id: str | None = None,
        cron_expression: str | None = None,
        timezone: str = "UTC",
        isolation_profile: ScheduledRunIsolationProfile | None = None,
        continuation_mode: ContinuationMode = ContinuationMode.NONE,
        continuation_origin: ScheduledResultOrigin | None = None,
    ) -> ScheduledTask:
        """Create a scheduled task the next scheduler tick will fire."""
        _require_floor(principal, "create_scheduled_task")
        task = ScheduledTask(
            task_id=task_id or f"task-{uuid4().hex[:12]}",
            name=name,
            interval_seconds=interval_seconds,
            event_type=event_type,
            created_by=principal.id,
            event_payload=dict(event_payload or {}),
            resource_ref=resource_ref,
            cron_expression=cron_expression,
            schedule_kind=ScheduleKind.CRON if cron_expression is not None else None,
            timezone=timezone,
            isolation_profile=isolation_profile or ScheduledRunIsolationProfile(),
            continuation_mode=continuation_mode,
            continuation_origin=continuation_origin,
        )
        if task_id is not None:
            try:
                existing = await self._store.get(task_id)
            except ScheduleNotFoundError:
                pass
            else:
                if existing == task:
                    return existing
                raise ValueError(f"task_id {task_id!r} already exists with different content")
        return await self._store.create(task)


__all__ = [
    "CreateIncidentCommand",
    "CreateScheduledTaskCommand",
    "CreationForbiddenError",
]
