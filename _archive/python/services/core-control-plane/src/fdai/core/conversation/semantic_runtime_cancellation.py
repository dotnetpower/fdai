"""Bridge task/request cancellation into thread-owned provider calls.

Every semantic planning and preflight call runs a synchronous model/provider
client on a worker thread via `asyncio.to_thread`. These helpers shield that
worker from cooperative cancellation, forward an external cancellation signal
into it, and drain an unresponsive worker in the background instead of
blocking the event loop past a short grace period.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from fdai_service_contracts.semantic_turn import SemanticConversationModelTier

from .adaptive_call_scope import bind_model_call_scope
from .conversation_preflight import ConversationPreflightResult
from .semantic_planning import SemanticPlanningService
from .semantic_planning_models import SemanticPlanningOutcome
from .session import Turn

_MODEL_THREAD_CANCELLATION_GRACE_SECONDS = 1.0
_PENDING_MODEL_THREAD_DRAINS: set[asyncio.Task[None]] = set()


async def _run_preflight_with_cancellation(
    planner: SemanticPlanningService,
    *,
    utterance: str,
    prior_turns: tuple[Turn, ...],
    locale: str,
    conversation_profile: Mapping[str, str] | None,
    cancelled: asyncio.Event | None,
    conversation_model_tier: SemanticConversationModelTier | None,
) -> ConversationPreflightResult:
    """Bridge task or request cancellation into the thread-owned provider call."""
    provider_cancelled = asyncio.Event()

    async def forward_request_cancellation() -> None:
        if cancelled is None:
            return
        await cancelled.wait()
        provider_cancelled.set()

    def invoke_preflight() -> ConversationPreflightResult:
        if conversation_model_tier is None:
            return planner.preflight(
                utterance=utterance,
                prior_turns=prior_turns,
                locale=locale,
                conversation_profile=conversation_profile,
                cancelled=provider_cancelled,
            )
        return planner.preflight(
            utterance=utterance,
            prior_turns=prior_turns,
            locale=locale,
            conversation_profile=conversation_profile,
            cancelled=provider_cancelled,
            conversation_model_tier=conversation_model_tier,
        )

    worker = asyncio.create_task(asyncio.to_thread(invoke_preflight))
    watcher = asyncio.create_task(forward_request_cancellation()) if cancelled is not None else None
    try:
        result = await asyncio.shield(worker)
        if provider_cancelled.is_set():
            raise asyncio.CancelledError
        return result
    except asyncio.CancelledError:
        provider_cancelled.set()
        try:
            await asyncio.wait_for(
                asyncio.shield(worker),
                timeout=_MODEL_THREAD_CANCELLATION_GRACE_SECONDS,
            )
        except TimeoutError:

            async def drain_worker() -> None:
                await asyncio.gather(worker, return_exceptions=True)

            drain = asyncio.create_task(drain_worker())
            _PENDING_MODEL_THREAD_DRAINS.add(drain)
            drain.add_done_callback(_PENDING_MODEL_THREAD_DRAINS.discard)
        raise
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


async def _run_planning_with_cancellation(
    operation: Callable[[], SemanticPlanningOutcome],
    *,
    cancelled: asyncio.Event | None,
) -> SemanticPlanningOutcome:
    """Cancel thread-owned Azure provider work when the request stops."""
    if cancelled is not None and cancelled.is_set():
        raise asyncio.CancelledError
    worker: asyncio.Task[SemanticPlanningOutcome] | None = None
    watcher = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
    try:
        async with bind_model_call_scope():
            worker = asyncio.create_task(asyncio.to_thread(operation))
            if watcher is None:
                return await asyncio.shield(worker)
            done, _pending = await asyncio.wait(
                {worker, watcher},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if watcher in done or (cancelled is not None and cancelled.is_set()):
                raise asyncio.CancelledError
            return worker.result()
    except asyncio.CancelledError:
        if worker is not None and not worker.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(worker),
                    timeout=_MODEL_THREAD_CANCELLATION_GRACE_SECONDS,
                )
            except TimeoutError:

                async def drain_worker() -> None:
                    await asyncio.gather(worker, return_exceptions=True)

                drain = asyncio.create_task(drain_worker())
                _PENDING_MODEL_THREAD_DRAINS.add(drain)
                drain.add_done_callback(_PENDING_MODEL_THREAD_DRAINS.discard)
        raise
    finally:
        if watcher is not None and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


__all__ = [
    "_run_planning_with_cancellation",
    "_run_preflight_with_cancellation",
]
