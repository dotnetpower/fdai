"""Safe-boundary workflow Process cancellation and compensation handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.workflow.compensation import WorkflowCompensationCoordinator
from fdai.core.workflow.workflow_runtime import WorkflowApprovalProvider, event_id
from fdai.shared.contracts.models import Workflow, WorkflowStepKind
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore


class WorkflowCancellationError(RuntimeError):
    """A Process cancellation request cannot advance safely."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class WorkflowCancellationProgress:
    snapshot: ProcessSnapshot
    waiting_for_outcome: bool = False


class WorkflowCancellationCoordinator:
    """Record cancellation intent and stop only at a durable safe boundary."""

    def __init__(
        self,
        *,
        process_store: ProcessRuntimeStore,
        audit_store: StateStore,
        approval_provider: WorkflowApprovalProvider | None,
        compensation: WorkflowCompensationCoordinator,
    ) -> None:
        self._process_store = process_store
        self._audit_store = audit_store
        self._approval_provider = approval_provider
        self._compensation = compensation

    async def request(
        self,
        *,
        snapshot: ProcessSnapshot,
        actor_oid: str,
        requested_at: datetime,
    ) -> ProcessSnapshot:
        events = await self._process_store.events(snapshot.process_id)
        if _cancellation_request(events) is not None:
            return snapshot
        if snapshot.status is ProcessStatus.CANCELLED:
            return snapshot
        if snapshot.status.terminal:
            raise WorkflowCancellationError(
                "process_not_cancellable",
                f"Process in {snapshot.status.value!r} state cannot be cancelled",
            )
        if snapshot.status not in {ProcessStatus.PENDING, ProcessStatus.WAITING}:
            raise WorkflowCancellationError(
                "process_not_at_safe_boundary",
                "Process cancellation requires a pending or waiting safe boundary",
            )
        actor = actor_oid.strip()
        if not actor:
            raise WorkflowCancellationError(
                "cancellation_actor_unavailable",
                "Process cancellation requires an authenticated actor",
            )
        await self._audit_store.append_audit_entry(
            {
                "event_id": event_id(snapshot.process_id, "cancellation:requested:audit"),
                "correlation_id": snapshot.correlation_id,
                "actor": actor,
                "action_kind": "workflow.process.cancellation-requested",
                "process_id": snapshot.process_id,
                "step_id": snapshot.current_step,
                "recorded_at": requested_at.isoformat(),
            }
        )
        return await self._process_store.transition(
            process_id=snapshot.process_id,
            expected_revision=snapshot.revision,
            status=snapshot.status,
            current_step=snapshot.current_step,
            event=ProcessEvent(
                event_id=event_id(snapshot.process_id, "cancellation:requested"),
                process_id=snapshot.process_id,
                kind=ProcessEventKind.PROCESS_CANCELLATION_REQUESTED,
                idempotency_key=f"{snapshot.process_id}:cancellation:requested",
                recorded_at=requested_at,
                correlation_id=snapshot.correlation_id,
                step_id=snapshot.current_step or None,
                payload={"actor_oid": actor},
            ),
        )

    async def advance(
        self,
        *,
        snapshot: ProcessSnapshot,
        workflow: Workflow,
        compensations: Mapping[str, str],
        context: Mapping[str, str],
    ) -> WorkflowCancellationProgress | None:
        events = await self._process_store.events(snapshot.process_id)
        request = _cancellation_request(events)
        if request is None or snapshot.status is ProcessStatus.COMPENSATING:
            return None
        if snapshot.status in {ProcessStatus.CANCELLED, ProcessStatus.COMPENSATED}:
            await self._close_approval(workflow=workflow, request=request)
            return WorkflowCancellationProgress(snapshot)
        if snapshot.status.terminal:
            raise WorkflowCancellationError(
                "process_cancellation_conflict",
                f"Process reached {snapshot.status.value!r} after cancellation was requested",
            )
        if _has_outstanding_action(events, snapshot.current_step):
            return WorkflowCancellationProgress(snapshot, waiting_for_outcome=True)
        recovery = await self._compensation.start(
            snapshot=snapshot,
            compensations=compensations,
            target_resource_id=snapshot.target_resource_id,
            context=context,
        )
        if recovery is not None:
            return WorkflowCancellationProgress(recovery.snapshot)
        cancelled_at = datetime.now(tz=UTC)
        await self._close_approval(workflow=workflow, request=request)
        cancelled = await self._process_store.transition(
            process_id=snapshot.process_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.CANCELLED,
            current_step="",
            event=ProcessEvent(
                event_id=event_id(snapshot.process_id, "cancelled"),
                process_id=snapshot.process_id,
                kind=ProcessEventKind.PROCESS_CANCELLED,
                idempotency_key=f"{snapshot.process_id}:cancelled",
                recorded_at=cancelled_at,
                correlation_id=snapshot.correlation_id,
                payload={"requested_event_id": request.event_id},
            ),
        )
        await self._audit_store.append_audit_entry(
            {
                "event_id": event_id(snapshot.process_id, "cancellation:completed:audit"),
                "correlation_id": snapshot.correlation_id,
                "actor": "fdai.core.workflow.cancellation",
                "action_kind": "workflow.process.cancelled",
                "process_id": snapshot.process_id,
                "requested_event_id": request.event_id,
                "recorded_at": cancelled_at.isoformat(),
            }
        )
        return WorkflowCancellationProgress(cancelled)

    async def _close_approval(self, *, workflow: Workflow, request: ProcessEvent) -> None:
        if request.step_id is None:
            return
        step = next((item for item in workflow.steps if item.id == request.step_id), None)
        if step is None or step.kind is not WorkflowStepKind.APPROVAL:
            return
        events = await self._process_store.events(request.process_id)
        if not any(
            event.kind is ProcessEventKind.APPROVAL_REQUESTED and event.step_id == request.step_id
            for event in events
        ):
            return
        if self._approval_provider is None:
            raise WorkflowCancellationError(
                "approval_cancellation_unavailable",
                "Workflow approval provider is unavailable during cancellation",
            )
        closed = await self._approval_provider.cancel_pending(
            process_id=request.process_id,
            step_id=request.step_id,
            cancelled_at=datetime.now(tz=UTC),
        )
        if not closed:
            raise WorkflowCancellationError(
                "approval_cancellation_conflict",
                "Workflow approval changed concurrently with Process cancellation",
            )


def _cancellation_request(events: tuple[ProcessEvent, ...]) -> ProcessEvent | None:
    return next(
        (
            event
            for event in events
            if event.kind is ProcessEventKind.PROCESS_CANCELLATION_REQUESTED
        ),
        None,
    )


def _has_outstanding_action(events: tuple[ProcessEvent, ...], step_id: str) -> bool:
    if not step_id:
        return False
    dispatched = any(
        event.kind is ProcessEventKind.ACTION_DISPATCHED and event.step_id == step_id
        for event in events
    )
    settled = any(
        event.step_id == step_id
        and event.kind in {ProcessEventKind.STEP_COMPLETED, ProcessEventKind.STEP_FAILED}
        for event in events
    )
    return dispatched and not settled


async def cancellation_blocks_new_step(
    *,
    process_store: ProcessRuntimeStore,
    process_id: str,
    step_id: str,
) -> bool:
    """Return whether cancellation blocks this step from starting new work."""
    events = await process_store.events(process_id)
    if _cancellation_request(events) is None:
        return False
    return not _has_outstanding_action(events, step_id)


__all__ = [
    "WorkflowCancellationCoordinator",
    "WorkflowCancellationError",
    "WorkflowCancellationProgress",
    "cancellation_blocks_new_step",
]
