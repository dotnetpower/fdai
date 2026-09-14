from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.human_assignment import GoalEvidence, HandoverGoal, HandoverGoalState
from fdai.runtime.handover_knowledge_lifecycle import HandoverKnowledgeLifecycleWorker
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)


class OperatorGoalSource:
    def __init__(self, store):
        self.store = store

    async def read_page(self, *, limit, offset):
        return await self.store.read_state_page(
            "operator-handover-goal:", limit=limit, offset=offset
        )


def _goal(
    *,
    goal_id: str,
    state: HandoverGoalState,
    revision: int = 1,
    evidence: tuple[GoalEvidence, ...] = (),
) -> HandoverGoal:
    return HandoverGoal(
        goal_id=goal_id,
        assignment_case_id="case-1",
        subject_ref="subject-1",
        agent_name="Muninn",
        scope_ref="scope:platform",
        prompt_ref="prompt:runbook",
        priority=90,
        created_at=_NOW,
        state=state,
        revision=revision,
        evidence=evidence,
    )


async def _events(bus: InMemoryEventBus, count: int):
    subscription = bus.subscribe("fdai.events", "test")
    return tuple([await anext(subscription) for _ in range(count)])


async def test_incomplete_goal_publishes_one_agent_owned_gap_once() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    goal = _goal(goal_id="goal-gap", state=HandoverGoalState.IN_PROGRESS)
    await store.write_state(f"handover_goal:goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(store=store, bus=bus, topic="fdai.events")

    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    (event,) = await _events(bus, 1)

    assert event.payload["source"] == "Muninn"
    assert event.payload["event_type"] == "knowledge.gap.raised"
    assert event.payload["payload"]["goal_ref"] == goal.goal_id
    assert "text" not in event.payload["payload"]


async def test_operator_owned_goal_prefix_is_processed_without_assignment_case() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    goal = _goal(goal_id="goal-operator", state=HandoverGoalState.NOT_STARTED)
    operator_value = goal.to_dict()
    operator_value.pop("assignment_case_id")
    operator_value["source_revision"] = "ownership-revision"
    await store.write_state("operator-handover-goal:goal-operator", operator_value)
    worker = HandoverKnowledgeLifecycleWorker(
        store=store, bus=bus, topic="fdai.events", operator_goals=OperatorGoalSource(store)
    )

    assert await worker.run_once() == 1
    (event,) = await _events(bus, 1)
    assert event.payload["event_type"] == "knowledge.gap.raised"
    assert event.payload["payload"]["assignment_case_ref"] is None


async def test_reviewable_goal_publishes_evidence_and_inert_candidates() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    goal = _goal(
        goal_id="goal-candidate",
        state=HandoverGoalState.READY_FOR_REVIEW,
        evidence=(
            GoalEvidence(
                evidence_ref="document:one",
                digest="a" * 64,
                kind="document_span",
            ),
        ),
    )
    await store.write_state(f"handover_goal:goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(store=store, bus=bus, topic="fdai.events")

    assert await worker.run_once() == 1
    events = await _events(bus, 3)

    assert [event.payload["source"] for event in events] == ["Muninn", "Mimir", "Norns"]
    candidates = events[1:]
    assert all(event.payload["payload"]["review_required"] for event in candidates)
    assert all(not event.payload["payload"]["may_promote"] for event in candidates)


async def test_stale_goal_publishes_evidence_withdrawal() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    goal = _goal(
        goal_id="goal-stale",
        state=HandoverGoalState.STALE,
        revision=2,
        evidence=(
            GoalEvidence(
                evidence_ref="document:one",
                digest="a" * 64,
                kind="document_span",
            ),
        ),
    )
    await store.write_state(f"handover_goal:goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(store=store, bus=bus, topic="fdai.events")

    assert await worker.run_once() == 1
    (event,) = await _events(bus, 1)
    assert event.payload["event_type"] == "knowledge.evidence.withdrawn"
    assert event.payload["payload"]["evidence_refs"] == ["document:one"]


async def test_invalid_goal_does_not_block_later_valid_goal() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    await store.write_state("handover_goal:goal:invalid", {"goal_id": "invalid"})
    goal = _goal(goal_id="goal-valid", state=HandoverGoalState.NOT_STARTED)
    await store.write_state(f"handover_goal:goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(store=store, bus=bus, topic="fdai.events")

    assert await worker.run_once() == 2
    assert await worker.run_once() == 0
    failures = await store.read_states("handover_knowledge_lifecycle_failure:", limit=10)
    assert failures == ({"failure_kind": "invalid_goal_record"},)


async def test_read_only_operator_projection_works_with_separate_goal_and_core_stores():
    core, operator, bus = InMemoryStateStore(), InMemoryStateStore(), InMemoryEventBus()
    goal = _goal(goal_id="goal-separated", state=HandoverGoalState.NOT_STARTED)
    await operator.write_state(f"operator-handover-goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(
        store=core, bus=bus, topic="fdai.events", operator_goals=OperatorGoalSource(operator)
    )
    assert await worker.run_once() == 1
    assert not await core.read_states("operator-handover-goal:", limit=10)
    assert not await operator.read_states("handover_knowledge_lifecycle:", limit=10)
    assert not tuple(operator.audit_entries)


async def test_already_published_rows_still_count_toward_the_scan_bound(monkeypatch):
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    for index in range(5):
        goal = _goal(goal_id=f"goal-{index}", state=HandoverGoalState.NOT_STARTED)
        await store.write_state(f"handover_goal:goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(
        store=store, bus=bus, topic="fdai.events", batch_limit=2
    )
    original = store.read_state_page
    page_sizes = []

    async def read_page(prefix, *, limit, offset=0):
        rows, count = await original(prefix, limit=limit, offset=offset)
        page_sizes.append(len(rows))
        return rows, count

    monkeypatch.setattr(store, "read_state_page", read_page)
    for _ in range(6):
        page_sizes.clear()
        await worker.run_once()
        assert sum(page_sizes) <= 2
    assert len(bus._records["fdai.events"]) == 5


async def test_busy_core_source_cannot_starve_operator_goals():
    core, operator, bus = InMemoryStateStore(), InMemoryStateStore(), InMemoryEventBus()
    for index in range(3):
        goal = _goal(goal_id=f"core-{index}", state=HandoverGoalState.NOT_STARTED)
        await core.write_state(f"handover_goal:goal:{goal.goal_id}", goal.to_dict())
    goal = _goal(goal_id="operator-only", state=HandoverGoalState.NOT_STARTED)
    await operator.write_state(f"operator-handover-goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(
        store=core,
        bus=bus,
        topic="fdai.events",
        batch_limit=1,
        operator_goals=OperatorGoalSource(operator),
    )
    await worker.run_once()
    await worker.run_once()
    assert any(
        item[1]["payload"]["goal_ref"] == goal.goal_id for item in bus._records["fdai.events"]
    )


async def test_failed_page_does_not_advance_the_scan_cursor(monkeypatch):
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    for index in range(2):
        goal = _goal(goal_id=f"goal-{index}", state=HandoverGoalState.NOT_STARTED)
        await store.write_state(f"handover_goal:goal:{goal.goal_id}", goal.to_dict())
    worker = HandoverKnowledgeLifecycleWorker(
        store=store, bus=bus, topic="fdai.events", batch_limit=1
    )
    original = bus.publish

    async def unavailable(*args, **kwargs):
        raise OSError("test bus unavailable")

    monkeypatch.setattr(bus, "publish", unavailable)
    with pytest.raises(OSError):
        await worker.run_once()
    assert worker._offsets == {}
    monkeypatch.setattr(bus, "publish", original)
    assert await worker.run_once() == 1


@pytest.mark.parametrize(
    "bad", [{"agent_name": "Unknown"}, {"evidence": [None]}, {"priority": True}]
)
async def test_malformed_goal_observation_never_produces_partial_candidates(bad):
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    goal = _goal(goal_id="invalid", state=HandoverGoalState.READY_FOR_REVIEW)
    await store.write_state("handover_goal:goal:invalid", {**goal.to_dict(), **bad})
    worker = HandoverKnowledgeLifecycleWorker(store=store, bus=bus, topic="fdai.events")
    assert await worker.run_once() == 1
    assert not bus._records
