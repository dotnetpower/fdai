"""JSON and SSE active-turn executors integrated with BusyInputCoordinator."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass

from fdai.core.conversation.busy_input import BusyInputMode, PendingBusyInput
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator

MAX_STEER_RERUNS = 3


@dataclass(frozen=True, slots=True)
class ActiveTurnExecutionResult:
    """Terminal result of one JSON or SSE turn coordinated by BusyInputCoordinator."""

    session_id: str
    turn_id: str
    status: str  # "completed" | "interrupted"
    committed_answer: str | None
    steer_reruns: int
    steered_inputs: tuple[str, ...]
    streamed_chunks: tuple[str, ...] = ()


class BusyInputActiveTurnExecutor:
    """Execute one-shot JSON and streaming SSE turns under BusyInputCoordinator."""

    def __init__(
        self,
        *,
        coordinator: BusyInputCoordinator,
        max_steer_reruns: int = MAX_STEER_RERUNS,
    ) -> None:
        if max_steer_reruns < 1:
            raise ValueError("max_steer_reruns must be >= 1")
        self._coordinator = coordinator
        self._max_steer_reruns = max_steer_reruns

    async def execute_json_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        principal_id: str,
        initial_prompt: str,
        step_runner: Callable[[str, tuple[str, ...]], Awaitable[str]],
        history_sink: list[str] | None = None,
        mode: BusyInputMode | None = None,
    ) -> ActiveTurnExecutionResult:
        """Execute a one-shot JSON turn with interrupt cleanup and bounded steer reruns."""
        active = await self._coordinator.begin_turn(
            session_id=session_id,
            turn_id=turn_id,
            principal_id=principal_id,
            mode=mode,
        )
        steered_contents: list[str] = []
        reruns = 0
        try:
            while True:
                if active.cancel_event.is_set():
                    return ActiveTurnExecutionResult(
                        session_id=session_id,
                        turn_id=turn_id,
                        status="interrupted",
                        committed_answer=None,
                        steer_reruns=reruns,
                        steered_inputs=tuple(steered_contents),
                    )
                try:
                    candidate_answer = await step_runner(initial_prompt, tuple(steered_contents))
                except asyncio.CancelledError:
                    if active.cancel_event.is_set():
                        return ActiveTurnExecutionResult(
                            session_id=session_id,
                            turn_id=turn_id,
                            status="interrupted",
                            committed_answer=None,
                            steer_reruns=reruns,
                            steered_inputs=tuple(steered_contents),
                        )
                    raise
                if active.cancel_event.is_set():
                    return ActiveTurnExecutionResult(
                        session_id=session_id,
                        turn_id=turn_id,
                        status="interrupted",
                        committed_answer=None,
                        steer_reruns=reruns,
                        steered_inputs=tuple(steered_contents),
                    )
                if reruns < self._max_steer_reruns:
                    steered: PendingBusyInput | None = await self._coordinator.safe_boundary(
                        session_id=session_id,
                        principal_id=principal_id,
                    )
                    if steered is not None:
                        steered_contents.append(steered.input.content)
                        reruns += 1
                        continue
                if history_sink is not None:
                    history_sink.append(candidate_answer)
                return ActiveTurnExecutionResult(
                    session_id=session_id,
                    turn_id=turn_id,
                    status="completed",
                    committed_answer=candidate_answer,
                    steer_reruns=reruns,
                    steered_inputs=tuple(steered_contents),
                )
        finally:
            await self._coordinator.finish_turn(
                session_id=session_id,
                turn_id=turn_id,
                principal_id=principal_id,
            )

    async def execute_sse_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        principal_id: str,
        initial_prompt: str,
        stream_factory: Callable[[str, tuple[str, ...]], AsyncIterable[str]],
        history_sink: list[str] | None = None,
        mode: BusyInputMode | None = None,
    ) -> ActiveTurnExecutionResult:
        """Execute an SSE streaming turn with safe-boundary steer reruns and interrupt cleanup."""
        active = await self._coordinator.begin_turn(
            session_id=session_id,
            turn_id=turn_id,
            principal_id=principal_id,
            mode=mode,
        )
        steered_contents: list[str] = []
        reruns = 0
        try:
            while True:
                chunks: list[str] = []
                restarted = False
                async for chunk in stream_factory(initial_prompt, tuple(steered_contents)):
                    if active.cancel_event.is_set():
                        return ActiveTurnExecutionResult(
                            session_id=session_id,
                            turn_id=turn_id,
                            status="interrupted",
                            committed_answer=None,
                            steer_reruns=reruns,
                            steered_inputs=tuple(steered_contents),
                            streamed_chunks=(),
                        )
                    chunks.append(chunk)
                    if reruns < self._max_steer_reruns:
                        steered = await self._coordinator.safe_boundary(
                            session_id=session_id,
                            principal_id=principal_id,
                        )
                        if steered is not None:
                            steered_contents.append(steered.input.content)
                            reruns += 1
                            restarted = True
                            break
                if restarted:
                    continue
                if active.cancel_event.is_set():
                    return ActiveTurnExecutionResult(
                        session_id=session_id,
                        turn_id=turn_id,
                        status="interrupted",
                        committed_answer=None,
                        steer_reruns=reruns,
                        steered_inputs=tuple(steered_contents),
                        streamed_chunks=(),
                    )
                final_answer = "".join(chunks)
                if history_sink is not None:
                    history_sink.append(final_answer)
                return ActiveTurnExecutionResult(
                    session_id=session_id,
                    turn_id=turn_id,
                    status="completed",
                    committed_answer=final_answer,
                    steer_reruns=reruns,
                    steered_inputs=tuple(steered_contents),
                    streamed_chunks=tuple(chunks),
                )
        finally:
            await self._coordinator.finish_turn(
                session_id=session_id,
                turn_id=turn_id,
                principal_id=principal_id,
            )


__all__ = [
    "ActiveTurnExecutionResult",
    "BusyInputActiveTurnExecutor",
    "MAX_STEER_RERUNS",
]
