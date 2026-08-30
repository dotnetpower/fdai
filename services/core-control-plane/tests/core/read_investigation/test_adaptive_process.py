from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
from fdai.core.rca.discrimination import (
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)
from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    build_adaptive_investigation_iteration,
    build_adaptive_investigation_result,
)
from fdai.core.read_investigation.adaptive_process import (
    ADAPTIVE_INVESTIGATION_WORKFLOW_REF,
    AdaptiveInvestigationProcessRecorder,
    project_adaptive_investigation_room,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

NOW = datetime(2026, 8, 30, tzinfo=UTC)
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"


def _budget() -> AdaptiveInvestigationBudget:
    return AdaptiveInvestigationBudget(
        max_rounds=3,
        max_queries=3,
        max_cost_units=100,
        deadline_at=NOW + timedelta(minutes=5),
        policy_digest=DIGEST_B,
    )


def _frame():
    return build_hypothesis_discrimination_frame(
        incident_id="incident-1",
        graph_revision="graph-1",
        evidence_cutoff=NOW,
        active_hypothesis_ids=("hypothesis-a", "hypothesis-b"),
        active_set_receipt_digest=DIGEST_A,
        cost_model_digest=DIGEST_B,
    )


def _iteration():
    frame = _frame()
    return build_adaptive_investigation_iteration(
        round_index=1,
        frame=frame,
        selection=select_discriminating_observation(frame, ()),
        execution=None,
        revision=None,
    )


def _result(iteration):
    frame = iteration.frame
    return build_adaptive_investigation_result(
        session_id="adaptive-1",
        incident_id="incident-1",
        workflow_version="1.0.0",
        active_strategy_digest=DIGEST_A,
        challenger_strategy_digest=None,
        budget=_budget(),
        iterations=(iteration,),
        disposition=AdaptiveInvestigationDisposition.HELD,
        terminal_frame_digest=frame.frame_digest,
        terminal_active_set_receipt_digest=frame.active_set_receipt_digest,
        used_queries=0,
        used_cost_units=0,
    )


def _recorder(store: InMemoryProcessRuntimeStore) -> AdaptiveInvestigationProcessRecorder:
    frame = _frame()
    return AdaptiveInvestigationProcessRecorder(
        store=store,
        session_id="adaptive-1",
        incident_id="incident-1",
        target_resource_id="resource-1",
        correlation_id="correlation-1",
        initial_frame=frame,
        active_strategy_digest=DIGEST_A,
        challenger_strategy_digest=None,
        budget=_budget(),
        planning_handoff_config_digest=DIGEST_A,
        clock=lambda: NOW,
    )


async def test_records_and_projects_read_only_investigation_room() -> None:
    store = InMemoryProcessRuntimeStore()
    recorder = _recorder(store)
    iteration = _iteration()

    await recorder.start()
    await recorder.record(iteration)
    result = _result(iteration)
    await recorder.record(result)

    snapshot = await store.get("adaptive-1")
    assert snapshot is not None
    assert snapshot.workflow_ref == ADAPTIVE_INVESTIGATION_WORKFLOW_REF
    assert snapshot.status is ProcessStatus.SUCCEEDED
    room = project_adaptive_investigation_room(await store.events("adaptive-1"))
    assert room is not None
    assert room["read_only"] is True
    assert room["mutation_controls"] is False
    assert room["round_count"] == 1
    assert room["terminal"]["disposition"] == "held"  # type: ignore[index]
    assert await recorder.replay_terminal_result() == result
    assert await recorder.planning_handoff_was_published("handoff-1") is False
    await recorder.record_planning_handoff_published("handoff-1")
    assert await recorder.planning_handoff_was_published("handoff-1") is True
    await recorder.record_planning_handoff_published("handoff-1")
    handoff_events = [
        event
        for event in await store.events("adaptive-1")
        if event.payload.get("record_type") == "adaptive_planning_handoff"
    ]
    assert len(handoff_events) == 1


async def test_iteration_order_is_enforced() -> None:
    store = InMemoryProcessRuntimeStore()
    recorder = _recorder(store)
    await recorder.start()
    iteration = _iteration()
    second = build_adaptive_investigation_iteration(
        round_index=2,
        frame=iteration.frame,
        selection=iteration.selection,
        execution=None,
        revision=None,
    )

    with pytest.raises(ValueError, match="out of order"):
        await recorder.record(second)


async def test_terminal_process_rejects_late_iteration() -> None:
    store = InMemoryProcessRuntimeStore()
    recorder = _recorder(store)
    iteration = _iteration()
    await recorder.start()
    await recorder.record(iteration)
    await recorder.record(_result(iteration))

    with pytest.raises(ValueError, match="not running"):
        await recorder.record(iteration)


async def test_terminal_process_rejects_result_with_substituted_strategy() -> None:
    store = InMemoryProcessRuntimeStore()
    recorder = _recorder(store)
    iteration = _iteration()
    await recorder.start()
    await recorder.record(iteration)
    substituted = build_adaptive_investigation_result(
        session_id="adaptive-1",
        incident_id="incident-1",
        workflow_version="1.0.0",
        active_strategy_digest=DIGEST_B,
        challenger_strategy_digest=None,
        budget=_budget(),
        iterations=(iteration,),
        disposition=AdaptiveInvestigationDisposition.HELD,
        terminal_frame_digest=iteration.frame.frame_digest,
        terminal_active_set_receipt_digest=(iteration.frame.active_set_receipt_digest),
        used_queries=0,
        used_cost_units=0,
    )

    with pytest.raises(ValueError, match="pinned session inputs"):
        await recorder.record(substituted)


async def test_reused_process_id_rejects_different_creation_identity() -> None:
    store = InMemoryProcessRuntimeStore()
    first = _recorder(store)
    await first.start()
    frame = _frame()
    conflicting = AdaptiveInvestigationProcessRecorder(
        store=store,
        session_id="adaptive-1",
        incident_id="incident-other",
        target_resource_id="resource-other",
        correlation_id="correlation-other",
        initial_frame=frame,
        active_strategy_digest=DIGEST_A,
        challenger_strategy_digest=None,
        budget=_budget(),
        planning_handoff_config_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="identity conflicts"):
        await conflicting.start()

    snapshot = await store.get("adaptive-1")
    assert snapshot is not None
    assert snapshot.target_resource_id == "resource-1"
    events = await store.events("adaptive-1")
    assert [event.kind.value for event in events] == [
        "process.created",
        "process.started",
    ]


async def test_stale_pending_start_is_reclaimed_with_cas() -> None:
    store = InMemoryProcessRuntimeStore()
    recorder = _recorder(store)
    await store.create(
        snapshot=ProcessSnapshot(
            process_id="adaptive-1",
            workflow_ref=ADAPTIVE_INVESTIGATION_WORKFLOW_REF,
            workflow_version="1.0.0",
            status=ProcessStatus.PENDING,
            current_step="context_frozen",
            target_resource_id="resource-1",
            started_at=NOW,
            updated_at=NOW,
            correlation_id="correlation-1",
        ),
        event=ProcessEvent(
            event_id=str(uuid5(NAMESPACE_URL, "adaptive-1:created")),
            process_id="adaptive-1",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="adaptive-1:created",
            recorded_at=NOW,
            correlation_id="correlation-1",
            payload=recorder._creation_payload(),  # noqa: SLF001
        ),
    )
    object.__setattr__(recorder, "_clock", lambda: NOW + timedelta(seconds=31))

    start = await recorder.start()

    assert start.replayed is False
    assert start.snapshot.status is ProcessStatus.RUNNING


def test_projection_rejects_broken_terminal_lineage() -> None:
    events = (
        {
            "payload": {
                "record_type": "adaptive_created",
                "incident_id": "incident-1",
                "active_strategy_digest": DIGEST_A,
                "budget": {},
            }
        },
        {
            "payload": {
                "record_type": "adaptive_terminal",
                "iteration_digests": ["sha256:missing"],
            }
        },
    )

    with pytest.raises(ValueError, match="terminal iteration lineage"):
        project_adaptive_investigation_room(events)
