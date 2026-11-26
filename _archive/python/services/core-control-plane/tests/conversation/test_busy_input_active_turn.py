"""Focused tests for JSON and SSE active-turn executors with BusyInputCoordinator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDisposition,
    BusyInputKind,
    BusyInputMode,
)
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation.busy_input_store import InMemoryBusyInputStore
from fdai.delivery.busy_input_active_turn import BusyInputActiveTurnExecutor

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _input(
    *,
    input_id: str,
    session_id: str = "sess-1",
    principal_id: str = "principal-a",
    content: str = "narrow to rg-prod",
) -> BusyInput:
    return BusyInput(
        input_id=input_id,
        idempotency_key=f"idem-{input_id}",
        session_id=session_id,
        principal_id=principal_id,
        content=content,
        kind=BusyInputKind.PROSE,
        received_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


async def test_json_active_turn_interrupt_discards_partial_assistant_history() -> None:
    store = InMemoryBusyInputStore()
    coordinator = BusyInputCoordinator(store=store)
    executor = BusyInputActiveTurnExecutor(coordinator=coordinator)
    history: list[str] = []

    async def _runner(prompt: str, steered: tuple[str, ...]) -> str:
        del prompt, steered
        decision = await coordinator.submit(
            _input(input_id="in-interrupt-1", content="stop and switch"),
            now=NOW,
        )
        assert decision.record.disposition is BusyInputDisposition.INTERRUPTING
        return "partial-assistant-reply-that-must-not-commit"

    result = await executor.execute_json_turn(
        session_id="sess-1",
        turn_id="turn-1",
        principal_id="principal-a",
        initial_prompt="initial question",
        step_runner=_runner,
        history_sink=history,
        mode=BusyInputMode.INTERRUPT,
    )
    assert result.status == "interrupted"
    assert result.committed_answer is None
    assert history == []


async def test_json_active_turn_bounded_steer_reruns_and_queue_fallback() -> None:
    store = InMemoryBusyInputStore()
    coordinator = BusyInputCoordinator(store=store)
    executor = BusyInputActiveTurnExecutor(coordinator=coordinator, max_steer_reruns=1)
    history: list[str] = []
    calls = 0

    async def _runner(prompt: str, steered: tuple[str, ...]) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            await coordinator.submit(
                _input(input_id="in-steer-1", content="filter region=koreacentral"),
                now=NOW,
            )
        elif calls == 2:
            # Second steer exceeds max_steer_reruns=1 and falls back to QUEUED on finish_turn
            await coordinator.submit(
                _input(input_id="in-steer-2", content="also includeaks"),
                now=NOW,
            )
        return f"{prompt}|{'+'.join(steered)}"

    result = await executor.execute_json_turn(
        session_id="sess-1",
        turn_id="turn-1",
        principal_id="principal-a",
        initial_prompt="list vms",
        step_runner=_runner,
        history_sink=history,
        mode=BusyInputMode.STEER,
    )
    assert result.status == "completed"
    assert result.steer_reruns == 1
    assert result.steered_inputs == ("filter region=koreacentral",)
    assert history == ["list vms|filter region=koreacentral"]

    # Verify the unconsumed second steer fell back to QUEUED after finish_turn
    pending = await coordinator.pending(session_id="sess-1", principal_id="principal-a")
    assert len(pending) == 1
    assert pending[0].input.input_id == "in-steer-2"
    assert pending[0].disposition is BusyInputDisposition.QUEUED


async def test_sse_active_turn_steer_restarts_stream_and_interrupt_cleans_up() -> None:
    store = InMemoryBusyInputStore()
    coordinator = BusyInputCoordinator(store=store)
    executor = BusyInputActiveTurnExecutor(coordinator=coordinator, max_steer_reruns=2)
    history: list[str] = []
    pass_count = 0

    async def _stream(prompt: str, steered: tuple[str, ...]) -> AsyncIterator[str]:
        nonlocal pass_count
        pass_count += 1
        if pass_count == 1:
            await coordinator.submit(
                _input(input_id="sse-steer-1", content="focus on AksCluster"),
                now=NOW,
            )
            yield "draft-chunk-1"
            yield "draft-chunk-2"
        else:
            yield f"{prompt}:"
            yield ",".join(steered)

    result = await executor.execute_sse_turn(
        session_id="sess-1",
        turn_id="turn-sse-1",
        principal_id="principal-a",
        initial_prompt="check health",
        stream_factory=_stream,
        history_sink=history,
        mode=BusyInputMode.STEER,
    )
    assert result.status == "completed"
    assert result.steer_reruns == 1
    assert result.committed_answer == "check health:focus on AksCluster"
    assert history == ["check health:focus on AksCluster"]
