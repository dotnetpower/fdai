from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.operational_planning import (
    PlanningPhase,
    PlanningPhaseOrderError,
    append_planning_phase,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

NOW = datetime(2026, 8, 3, tzinfo=UTC)


async def _process() -> tuple[InMemoryProcessRuntimeStore, ProcessSnapshot]:
    store = InMemoryProcessRuntimeStore()
    snapshot, _created = await store.create(
        snapshot=ProcessSnapshot(
            process_id="planning-example",
            workflow_ref="operational-planning",
            workflow_version="1.0.0",
            status=ProcessStatus.RUNNING,
            current_step="plan",
            target_resource_id="resource-example",
            started_at=NOW,
            updated_at=NOW,
            correlation_id="correlation-example",
        ),
        event=ProcessEvent(
            event_id="created",
            process_id="planning-example",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="planning-example:created",
            recorded_at=NOW,
            correlation_id="correlation-example",
        ),
    )
    return store, snapshot


async def _append(
    store: InMemoryProcessRuntimeStore,
    snapshot: ProcessSnapshot,
    phase: PlanningPhase,
) -> bool:
    return await append_planning_phase(
        store=store,
        snapshot=snapshot,
        phase=phase,
        actor_agent="Forseti",
        decision_case_id="case-example",
        context_digest="a" * 64,
        logic_release_digest="sha256:" + "b" * 64,
        evidence_refs=("evidence:1",),
        recorded_at=NOW,
    )


async def test_planning_phases_are_ordered_idempotent_child_events() -> None:
    store, snapshot = await _process()
    phases = (
        PlanningPhase.CONTEXT_FROZEN,
        PlanningPhase.PROPOSALS_COLLECTED,
        PlanningPhase.SIMULATIONS_CLOSED,
        PlanningPhase.CRITIQUES_CLOSED,
        PlanningPhase.ARBITRATION_CLOSED,
        PlanningPhase.SELECTED,
    )

    for phase in phases:
        assert await _append(store, snapshot, phase) is True
    assert await _append(store, snapshot, PlanningPhase.SELECTED) is False
    events = await store.events(snapshot.process_id)

    assert [event.payload.get("planning_phase") for event in events[1:]] == [
        phase.value for phase in phases
    ]
    assert (await store.get(snapshot.process_id)).revision == snapshot.revision


async def test_out_of_order_or_post_terminal_phase_fails_closed() -> None:
    store, snapshot = await _process()
    with pytest.raises(PlanningPhaseOrderError, match="requires"):
        await _append(store, snapshot, PlanningPhase.SIMULATIONS_CLOSED)

    for phase in (
        PlanningPhase.CONTEXT_FROZEN,
        PlanningPhase.PROPOSALS_COLLECTED,
        PlanningPhase.SIMULATIONS_CLOSED,
        PlanningPhase.CRITIQUES_CLOSED,
        PlanningPhase.ARBITRATION_CLOSED,
        PlanningPhase.HELD,
    ):
        await _append(store, snapshot, phase)
    with pytest.raises(PlanningPhaseOrderError, match="terminal"):
        await _append(store, snapshot, PlanningPhase.ABSTAINED)
