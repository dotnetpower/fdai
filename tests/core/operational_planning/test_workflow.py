from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.operational_planning import ProcessPlanningRecorder, SpecialistPlanningCoordinator
from fdai.shared.providers.process_runtime import ProcessStatus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

from .test_coordinator import _context, _PassedConstraints, _Simulator

NOW = datetime(2026, 8, 3, tzinfo=UTC)


async def test_planning_coordinator_records_complete_replayable_process() -> None:
    store = InMemoryProcessRuntimeStore()
    ticks = iter(NOW + timedelta(seconds=index) for index in range(20))
    recorder = ProcessPlanningRecorder(store=store, clock=lambda: next(ticks))
    coordinator = SpecialistPlanningCoordinator(
        logic_release_digest="sha256:" + "c" * 64,
        constraint_evaluator=_PassedConstraints(),
        simulator=_Simulator(),
        recorder=recorder,
    )
    values = dict(
        correlation_id="planning-workflow",
        context=_context(),
        advice={"cost": "scale_down", "capacity": "scale_up"},
        impacts={"cost": 0.2, "capacity": 0.9},
        created_at=NOW,
    )

    first = await coordinator.build(**values)
    replay = await coordinator.build(**values)

    assert first is not None and replay is not None
    assert replay.plan.plan_id == first.plan.plan_id
    snapshot = await store.get(first.plan.process_id)
    assert snapshot is not None
    assert snapshot.status is ProcessStatus.SUCCEEDED
    events = await store.events(first.plan.process_id)
    planning_phases = [
        event.payload.get("planning_phase") for event in events if "planning_phase" in event.payload
    ]
    assert planning_phases == [
        "context_frozen",
        "proposals_collected",
        "simulations_closed",
        "critiques_closed",
        "arbitration_closed",
        "selected",
    ]
    assert sum(event.kind.value == "process.completed" for event in events) == 1


async def test_recorder_rejects_conflicting_replay() -> None:
    store = InMemoryProcessRuntimeStore()
    recorder = ProcessPlanningRecorder(store=store, clock=lambda: NOW)
    coordinator = SpecialistPlanningCoordinator(
        logic_release_digest="sha256:" + "c" * 64,
        constraint_evaluator=_PassedConstraints(),
        simulator=_Simulator(),
        recorder=recorder,
    )
    values = dict(
        correlation_id="planning-conflict",
        context=_context(),
        advice={"cost": "scale_down", "capacity": "scale_up"},
        impacts={"cost": 0.2, "capacity": 0.9},
        created_at=NOW,
    )
    first = await coordinator.build(**values)
    assert first is not None

    with pytest.raises(ValueError, match="conflicts"):
        await coordinator.build(**{**values, "impacts": {"cost": 0.9, "capacity": 0.1}})
