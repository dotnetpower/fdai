"""Replay-safe Process child events for operational-planning phases."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
)

from .models import OperationalPlan, PlanningPhase
from .projection import operational_plan_event_payload

_ORDER = (
    PlanningPhase.CONTEXT_FROZEN,
    PlanningPhase.PROPOSALS_COLLECTED,
    PlanningPhase.SIMULATIONS_CLOSED,
    PlanningPhase.CRITIQUES_CLOSED,
    PlanningPhase.ARBITRATION_CLOSED,
)
_TERMINAL = frozenset({PlanningPhase.SELECTED, PlanningPhase.HELD, PlanningPhase.ABSTAINED})


class PlanningPhaseOrderError(ValueError):
    """A planning phase arrived without its required predecessor."""


async def append_planning_phase(
    *,
    store: ProcessRuntimeStore,
    snapshot: ProcessSnapshot,
    phase: PlanningPhase,
    actor_agent: str,
    decision_case_id: str,
    context_digest: str,
    logic_release_digest: str,
    evidence_refs: tuple[str, ...],
    recorded_at: datetime,
    plan: OperationalPlan | None = None,
) -> bool:
    if snapshot.status.terminal:
        raise PlanningPhaseOrderError("terminal Process cannot accept planning phases")
    if recorded_at.tzinfo is None:
        raise ValueError("planning phase timestamp MUST be timezone-aware")
    if not all((actor_agent, decision_case_id, context_digest, logic_release_digest)):
        raise ValueError("planning phase identities MUST be non-empty")
    if not evidence_refs:
        raise ValueError("planning phase requires evidence")
    events = await store.events(snapshot.process_id)
    recorded = tuple(
        PlanningPhase(str(event.payload["planning_phase"]))
        for event in events
        if event.kind is ProcessEventKind.PLANNING_PHASE_RECORDED
        and "planning_phase" in event.payload
    )
    if phase in recorded:
        return False
    if any(item in _TERMINAL for item in recorded):
        raise PlanningPhaseOrderError("terminal planning phase already recorded")
    predecessor: PlanningPhase | None
    if phase in _TERMINAL:
        predecessor = PlanningPhase.ARBITRATION_CLOSED
    else:
        index = _ORDER.index(phase)
        predecessor = _ORDER[index - 1] if index else None
    if predecessor is not None and predecessor not in recorded:
        raise PlanningPhaseOrderError(
            f"planning phase {phase.value!r} requires {predecessor.value!r}"
        )
    identity = f"{snapshot.process_id}:planning:{phase.value}"
    if plan is not None:
        if plan.process_id != snapshot.process_id:
            raise ValueError("operational plan process does not match planning phase")
        if plan.decision_case.case_id != decision_case_id:
            raise ValueError("operational plan DecisionCase does not match planning phase")
        if plan.logic_release_digest != logic_release_digest:
            raise ValueError("operational plan release does not match planning phase")
    payload: dict[str, object] = {
        "planning_phase": phase.value,
        "actor_agent": actor_agent,
        "decision_case_id": decision_case_id,
        "context_digest": context_digest,
        "logic_release_digest": logic_release_digest,
        "evidence_refs": list(evidence_refs),
    }
    if plan is not None:
        payload["operational_plan"] = operational_plan_event_payload(plan)
    return await store.append_event(
        ProcessEvent(
            event_id=str(uuid5(NAMESPACE_URL, identity)),
            process_id=snapshot.process_id,
            kind=ProcessEventKind.PLANNING_PHASE_RECORDED,
            idempotency_key=identity,
            recorded_at=recorded_at,
            correlation_id=snapshot.correlation_id,
            payload=payload,
        )
    )


__all__ = ["PlanningPhaseOrderError", "append_planning_phase"]
