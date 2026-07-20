"""RBAC-scoped operator console tools for scheduled tasks (P2-6).

Lets an operator create / list / cancel recurring monitoring tasks from the
conversational console (``operator-console.md`` 3.2). Each tool operates on
the shared :class:`~fdai.core.scheduler.store.ScheduleStore`, so a task
created from chat is picked up by the next
:class:`~fdai.core.scheduler.service.SchedulerService` tick (Container Apps
Job cron in production). Creating a schedule never executes a change - the
task, when due, only injects a synthetic event into the standard control
loop, which the risk gate governs.

These tools are **async** (they touch the async store), unlike the Day-1
read-only sync :class:`~fdai.core.conversation.tools.SystemConsoleTool`.
Each declares an ``rbac_floor`` and enforces it internally via
:func:`~fdai.core.conversation.session.principal_has_role_at_least`, so a
below-floor caller gets a structured ``error`` :class:`ToolResult` and the
store is never touched. The caller writes exactly one audit entry per call
(the tool returns ``evidence_refs`` and a ``preview`` for that record).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Final

from fdai.core.conversation.session import (
    Principal,
    Role,
    principal_has_role_at_least,
)
from fdai.core.conversation.tools import SideEffectClass, ToolResult
from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.service import SchedulerService
from fdai.core.scheduler.store import ScheduleNotFoundError, ScheduleStore

_MIN_INTERVAL_SECONDS: Final[float] = 60.0


def _task_view(task: ScheduledTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "name": task.name,
        "interval_seconds": task.interval_seconds,
        "event_type": task.event_type,
        "created_by": task.created_by,
        "resource_ref": task.resource_ref,
        "enabled": task.enabled,
        "last_run": task.last_run.isoformat() if task.last_run else None,
        "cron_expression": task.cron_expression,
    }


def _deny(tool: str, floor: Role) -> ToolResult:
    return ToolResult(
        status="error",
        preview=f"{tool} requires role >= {floor.value}",
    )


class CreateScheduleTool:
    """Create a recurring monitoring task.

    Arguments:

    - ``name`` (str, required)
    - ``interval_seconds`` (number, required, >= 60)
    - ``event_type`` (str, required) - the synthetic event type fired each tick
    - ``resource_ref`` (str, optional)
    - ``event_payload`` (mapping, optional)
    """

    name = "create_schedule"
    description = (
        "Create a recurring monitoring task that fires a synthetic event each "
        "interval; the standard trust-router + risk-gate govern any action."
    )
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "execute"

    def __init__(self, *, store: ScheduleStore, id_factory: Any = None) -> None:
        self._store = store
        # Injected so tests get deterministic ids; defaults to uuid4 hex.
        if id_factory is None:
            from uuid import uuid4

            id_factory = lambda: uuid4().hex  # noqa: E731
        self._id_factory = id_factory

    async def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        if not principal_has_role_at_least(principal.role, self.rbac_floor):
            return _deny(self.name, self.rbac_floor)

        name = str(arguments.get("name") or "").strip()
        event_type = str(arguments.get("event_type") or "").strip()
        if not name or not event_type:
            return ToolResult(
                status="error",
                preview="create_schedule requires 'name' and 'event_type'.",
            )
        cron_expression = str(arguments.get("cron_expression") or "").strip() or None
        try:
            interval = float(arguments.get("interval_seconds", _MIN_INTERVAL_SECONDS))
        except (TypeError, ValueError):
            return ToolResult(
                status="error", preview="create_schedule 'interval_seconds' must be a number."
            )
        if interval < _MIN_INTERVAL_SECONDS:
            return ToolResult(
                status="error",
                preview=f"interval_seconds must be >= {int(_MIN_INTERVAL_SECONDS)}.",
            )

        payload = arguments.get("event_payload")
        resource_ref_arg = arguments.get("resource_ref")
        task = ScheduledTask(
            task_id=self._id_factory(),
            name=name,
            interval_seconds=interval,
            event_type=event_type,
            created_by=principal.id,
            event_payload=dict(payload) if isinstance(payload, Mapping) else {},
            resource_ref=str(resource_ref_arg) if resource_ref_arg else None,
            cron_expression=cron_expression,
        )
        created = await self._store.create(task)
        return ToolResult(
            status="ok",
            data={"task": _task_view(created)},
            preview=f"created schedule {created.task_id} ({created.name})",
            evidence_refs=(f"schedule:{created.task_id}",),
        )


class ListSchedulesTool:
    """List scheduled tasks (read-only)."""

    name = "list_schedules"
    description = "List all scheduled monitoring tasks with their next-run state."
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, store: ScheduleStore) -> None:
        self._store = store

    async def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        del arguments
        if not principal_has_role_at_least(principal.role, self.rbac_floor):
            return _deny(self.name, self.rbac_floor)
        tasks = await self._store.list_all()
        return ToolResult(
            status="ok",
            data={"tasks": [_task_view(t) for t in tasks]},
            preview=f"{len(tasks)} scheduled task(s)",
        )


class CancelScheduleTool:
    """Cancel (delete) a scheduled task by id."""

    name = "cancel_schedule"
    description = "Cancel a scheduled monitoring task by its task_id."
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "execute"

    def __init__(self, *, store: ScheduleStore) -> None:
        self._store = store

    async def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        if not principal_has_role_at_least(principal.role, self.rbac_floor):
            return _deny(self.name, self.rbac_floor)
        task_id = str(arguments.get("task_id") or "").strip()
        if not task_id:
            return ToolResult(status="error", preview="cancel_schedule requires 'task_id'.")
        try:
            await self._store.cancel(task_id)
        except ScheduleNotFoundError:
            return ToolResult(status="error", preview=f"no scheduled task {task_id!r}")
        return ToolResult(
            status="ok",
            data={"task_id": task_id},
            preview=f"cancelled schedule {task_id}",
            evidence_refs=(f"schedule:{task_id}",),
        )


class SetScheduleEnabledTool:
    """Pause or resume one schedule without deleting its definition."""

    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "execute"

    def __init__(self, *, store: ScheduleStore, enabled: bool) -> None:
        self._store = store
        self._enabled = enabled
        self.name = "resume_schedule" if enabled else "pause_schedule"
        self.description = f"{'Resume' if enabled else 'Pause'} a scheduled monitoring task."

    async def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        if not principal_has_role_at_least(principal.role, self.rbac_floor):
            return _deny(self.name, self.rbac_floor)
        task_id = str(arguments.get("task_id") or "").strip()
        if not task_id:
            return ToolResult(status="error", preview=f"{self.name} requires 'task_id'.")
        try:
            current = await self._store.get(task_id)
            updated = await self._store.update(replace(current, enabled=self._enabled))
        except ScheduleNotFoundError:
            return ToolResult(status="error", preview=f"no scheduled task {task_id!r}")
        state = "resumed" if self._enabled else "paused"
        return ToolResult(
            status="ok",
            data={"task": _task_view(updated)},
            preview=f"{state} schedule {task_id}",
            evidence_refs=(f"schedule:{task_id}",),
        )


class UpdateScheduleTool:
    """Edit bounded schedule fields while preserving identity and history."""

    name = "update_schedule"
    description = "Edit a schedule name, interval, event type, resource, cron, or timezone."
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "execute"

    def __init__(self, *, store: ScheduleStore) -> None:
        self._store = store

    async def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        if not principal_has_role_at_least(principal.role, self.rbac_floor):
            return _deny(self.name, self.rbac_floor)
        task_id = str(arguments.get("task_id") or "").strip()
        if not task_id:
            return ToolResult(status="error", preview="update_schedule requires 'task_id'.")
        try:
            current = await self._store.get(task_id)
            interval = float(arguments.get("interval_seconds", current.interval_seconds))
            if interval < _MIN_INTERVAL_SECONDS:
                raise ValueError(f"interval_seconds must be >= {int(_MIN_INTERVAL_SECONDS)}")
            updated = replace(
                current,
                name=str(arguments.get("name", current.name)).strip(),
                interval_seconds=interval,
                event_type=str(arguments.get("event_type", current.event_type)).strip(),
                resource_ref=(
                    str(arguments["resource_ref"]).strip() or None
                    if "resource_ref" in arguments
                    else current.resource_ref
                ),
                cron_expression=(
                    str(arguments["cron_expression"]).strip() or None
                    if "cron_expression" in arguments
                    else current.cron_expression
                ),
                timezone=str(arguments.get("timezone", current.timezone)).strip(),
            )
            updated = await self._store.update(updated)
        except ScheduleNotFoundError:
            return ToolResult(status="error", preview=f"no scheduled task {task_id!r}")
        except (TypeError, ValueError) as exc:
            return ToolResult(status="error", preview=f"invalid schedule update: {exc}")
        return ToolResult(
            status="ok",
            data={"task": _task_view(updated)},
            preview=f"updated schedule {task_id}",
            evidence_refs=(f"schedule:{task_id}",),
        )


class RunScheduleNowTool:
    """Immediately dispatch a schedule through its normal event path."""

    name = "run_schedule_now"
    description = "Run one enabled scheduled task now through the normal control loop."
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "execute"

    def __init__(self, *, scheduler: SchedulerService) -> None:
        self._scheduler = scheduler

    async def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        if not principal_has_role_at_least(principal.role, self.rbac_floor):
            return _deny(self.name, self.rbac_floor)
        task_id = str(arguments.get("task_id") or "").strip()
        idempotency_key = str(arguments.get("idempotency_key") or "").strip()
        if not task_id or not idempotency_key:
            return ToolResult(
                status="error",
                preview="run_schedule_now requires 'task_id' and 'idempotency_key'.",
            )
        try:
            report = await self._scheduler.run_task_now(
                task_id,
                idempotency_key=idempotency_key,
            )
        except (ScheduleNotFoundError, ValueError) as exc:
            return ToolResult(status="error", preview=f"run_schedule_now failed: {exc}")
        return ToolResult(
            status="ok",
            data={"task_id": task_id, "fired": report.fired},
            preview=f"ran schedule {task_id} now",
            evidence_refs=(f"schedule:{task_id}",),
        )


__all__ = [
    "CancelScheduleTool",
    "CreateScheduleTool",
    "ListSchedulesTool",
    "RunScheduleNowTool",
    "SetScheduleEnabledTool",
    "UpdateScheduleTool",
]
