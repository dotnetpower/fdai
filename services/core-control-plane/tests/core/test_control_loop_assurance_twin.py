from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any, cast

import fdai.core.control_loop.orchestrator as orchestrator_module
from fdai.core.assurance_twin import CompletePostureEvaluation, build_baseline_projection
from fdai.core.control_loop._rule_generation import RuleGenerationBarrier
from fdai.core.control_loop.orchestrator import ControlLoop
from fdai.core.event_ingest import EventIngest
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import RuleIndex, T0Engine
from fdai.core.trust_router import TrustRouter
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def test_posture_generation_does_not_consume_control_loop_replay_clock() -> None:
    calls = 0

    def replay_clock() -> datetime:
        nonlocal calls
        calls += 1
        return datetime(2026, 7, 5, tzinfo=UTC)

    index = RuleIndex.build(())
    ControlLoop(
        event_ingest=EventIngest(validator=cast(Any, object())),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index),
        action_builder=ActionBuilder(action_types_by_name={}, clock=replay_clock),
        executor=cast(Any, object()),
        audit_store=InMemoryStateStore(),
        rules_by_id={},
        clock=replay_clock,
    )

    assert calls == 0


async def test_complete_posture_evaluation_does_not_block_event_loop(
    monkeypatch: Any,
) -> None:
    started = threading.Event()
    release = threading.Event()
    expected = CompletePostureEvaluation(
        findings=(),
        evaluated_rule_ids=("rule.example",),
        rule_set_digest="sha256:" + "a" * 64,
        rule_generation_digest="sha256:" + "d" * 64,
        rule_generation_time=orchestrator_module.datetime.now(orchestrator_module.UTC),
        coverage_refs=("sha256:" + "b" * 64,),
    )

    def evaluate(**_kwargs: object) -> CompletePostureEvaluation:
        started.set()
        if not release.wait(timeout=1):
            raise TimeoutError("test did not release evaluation thread")
        return expected

    monkeypatch.setattr(orchestrator_module, "evaluate_complete_posture", evaluate)
    loop = cast(Any, object.__new__(ControlLoop))
    loop._rule_generation_barrier = RuleGenerationBarrier()
    loop._t0_engine = object()
    loop._rules_by_id = {}
    loop._rule_generation_time = expected.rule_generation_time

    task = asyncio.create_task(
        loop.evaluate_assurance_twin_posture(
            projection=build_baseline_projection(()),
            inventory_revision="sha256:" + "c" * 64,
        )
    )
    for _ in range(50):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()
    async with asyncio.timeout(0.5):
        async with loop._rule_generation_barrier.write():
            pass
    release.set()
    assert await task == expected
