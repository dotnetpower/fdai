"""Durable Process recording for completed operational-planning runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.core.operational_context import OperationalContextSnapshot
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)

from .coordinator import SpecialistPlanningProjection
from .journal import append_planning_phase
from .models import PlanningPhase
from .projection import project_planning_room

_WORKFLOW_REF = "operational-planning"
_WORKFLOW_VERSION = "1.0.0"


class ProcessPlanningRecorder:
    """Record one immutable plan without becoming a decision or execution authority."""

    def __init__(
        self,
        *,
        store: ProcessRuntimeStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def record(
        self,
        *,
        projection: SpecialistPlanningProjection,
        context: OperationalContextSnapshot,
        recorded_at: datetime,
    ) -> None:
        plan = projection.plan
        if context.snapshot_id != plan.decision_case.context_snapshot_id:
            raise ValueError("planning context does not match DecisionCase")
        now = self._clock()
        snapshot, created = await self._store.create(
            snapshot=ProcessSnapshot(
                process_id=plan.process_id,
                workflow_ref=_WORKFLOW_REF,
                workflow_version=_WORKFLOW_VERSION,
                status=ProcessStatus.PENDING,
                current_step="planning",
                target_resource_id=context.target_resource_id,
                started_at=recorded_at,
                updated_at=now,
                correlation_id=plan.decision_case.correlation_id,
            ),
            event=ProcessEvent(
                event_id=_event_id(plan.process_id, "created"),
                process_id=plan.process_id,
                kind=ProcessEventKind.PROCESS_CREATED,
                idempotency_key=f"{plan.process_id}:created",
                recorded_at=now,
                correlation_id=plan.decision_case.correlation_id,
                payload={
                    "workflow_ref": _WORKFLOW_REF,
                    "workflow_version": _WORKFLOW_VERSION,
                    "context_snapshot_id": context.snapshot_id,
                    "logic_release_digest": plan.logic_release_digest,
                },
            ),
        )
        if snapshot.status.terminal:
            await self._verify_replay(snapshot=snapshot, expected_plan_id=plan.plan_id)
            return
        if snapshot.status is ProcessStatus.PENDING:
            snapshot = await self._store.transition(
                process_id=snapshot.process_id,
                expected_revision=snapshot.revision,
                status=ProcessStatus.RUNNING,
                current_step="planning",
                event=ProcessEvent(
                    event_id=_event_id(plan.process_id, "started"),
                    process_id=plan.process_id,
                    kind=ProcessEventKind.PROCESS_STARTED,
                    idempotency_key=f"{plan.process_id}:started",
                    recorded_at=self._clock(),
                    correlation_id=plan.decision_case.correlation_id,
                ),
            )
        elif snapshot.status is not ProcessStatus.RUNNING:
            raise ValueError("operational-planning Process is not resumable")
        terminal_phase = PlanningPhase.SELECTED if plan.complete else PlanningPhase.HELD
        phases = (
            PlanningPhase.CONTEXT_FROZEN,
            PlanningPhase.PROPOSALS_COLLECTED,
            PlanningPhase.SIMULATIONS_CLOSED,
            PlanningPhase.CRITIQUES_CLOSED,
            PlanningPhase.ARBITRATION_CLOSED,
            terminal_phase,
        )
        for phase in phases:
            await append_planning_phase(
                store=self._store,
                snapshot=snapshot,
                phase=phase,
                actor_agent="Forseti",
                decision_case_id=plan.decision_case.case_id,
                context_digest=context.snapshot_id,
                logic_release_digest=plan.logic_release_digest,
                evidence_refs=plan.decision_case.evidence_refs,
                recorded_at=self._clock(),
                plan=plan if phase is terminal_phase else None,
            )
        current = await self._store.get(plan.process_id)
        if current is None:
            raise RuntimeError("operational-planning Process disappeared before closure")
        if current.status.terminal:
            await self._verify_replay(snapshot=current, expected_plan_id=plan.plan_id)
            return
        await self._store.transition(
            process_id=current.process_id,
            expected_revision=current.revision,
            status=ProcessStatus.SUCCEEDED,
            current_step="",
            event=ProcessEvent(
                event_id=_event_id(plan.process_id, "completed"),
                process_id=plan.process_id,
                kind=ProcessEventKind.PROCESS_COMPLETED,
                idempotency_key=f"{plan.process_id}:completed",
                recorded_at=self._clock(),
                correlation_id=plan.decision_case.correlation_id,
                payload={
                    "planning_outcome": plan.reason,
                    "plan_id": plan.plan_id,
                    "selected_option_id": plan.selection.selected_option_id,
                },
            ),
        )
        if not created:
            await self._verify_replay(
                snapshot=await self._required_snapshot(plan.process_id),
                expected_plan_id=plan.plan_id,
            )

    async def _verify_replay(
        self,
        *,
        snapshot: ProcessSnapshot,
        expected_plan_id: str,
    ) -> None:
        planning = project_planning_room(await self._store.events(snapshot.process_id))
        actual_plan = planning.get("plan") if planning is not None else None
        actual_plan_id = actual_plan.get("plan_id") if isinstance(actual_plan, dict) else None
        if actual_plan_id != expected_plan_id:
            raise ValueError("operational-planning replay conflicts with persisted plan")

    async def _required_snapshot(self, process_id: str) -> ProcessSnapshot:
        snapshot = await self._store.get(process_id)
        if snapshot is None:
            raise RuntimeError("operational-planning Process disappeared")
        return snapshot


def _event_id(process_id: str, suffix: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{process_id}:{suffix}"))


__all__ = ["ProcessPlanningRecorder"]
