"""Overlap the semantic form path with the conversation preflight for one turn.

The preflight still routes the turn. A started form-path ticket is adopted only by the turn's
first verified read of the same question; every other route cancels it when the turn ends.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from typing import Any, Concatenate, Protocol

from .semantic_compiled_answers import CompiledAnswerTicket

_LOGGER = logging.getLogger(__name__)


class _SpeculativePlanner(Protocol):
    @property
    def speculative_form_enabled(self) -> bool: ...

    def start_speculative_form(self, **arguments: Any) -> CompiledAnswerTicket | None: ...


class SpeculativeForm:
    """One turn's speculative ticket, taken at most once for the exact original question."""

    def __init__(self, utterance: str, task: asyncio.Task[CompiledAnswerTicket | None]) -> None:
        self._utterance = utterance
        self._task = task
        self._taken = False

    async def take(self, question: str) -> CompiledAnswerTicket | None:
        if self._taken or question != self._utterance:
            return None
        self._taken = True
        try:
            return await self._task
        except Exception:  # noqa: BLE001 - a failed speculation falls back to the normal start
            _LOGGER.warning("semantic_speculative_form_unavailable")
            return None

    def release(self) -> None:
        """Cancel a ticket that no verified read adopted."""

        if self._taken:
            return
        self._taken = True

        def cancel(task: asyncio.Task[CompiledAnswerTicket | None]) -> None:
            if not task.cancelled() and task.exception() is None and task.result() is not None:
                task.result().cancel()  # type: ignore[union-attr]

        if self._task.done():
            cancel(self._task)
        else:
            self._task.add_done_callback(cancel)


_CURRENT: ContextVar[SpeculativeForm | None] = ContextVar("semantic_speculative_form", default=None)


async def take_speculative_form(question: str) -> CompiledAnswerTicket | None:
    """Return the current turn's ticket for ``question`` once, or ``None``."""

    current = _CURRENT.get()
    return await current.take(question) if current is not None else None


def speculative_form_start[**P, R](
    method: Callable[Concatenate[Any, P], Coroutine[Any, Any, R]],
) -> Callable[Concatenate[Any, P], Coroutine[Any, Any, R]]:
    """Start an eligible turn's form path in a worker thread before ``method`` runs."""

    @functools.wraps(method)
    async def wrapper(self: Any, /, *args: P.args, **kwargs: P.kwargs) -> R:
        planner: _SpeculativePlanner | None = getattr(self, "_planner", None)
        # A planner without the opt-in setting never speculates.
        eligible = (
            planner is not None
            and getattr(planner, "speculative_form_enabled", False) is True
            and kwargs.get("bound_incident") is None
            and kwargs.get("bound_resource_context") is None
            and kwargs.get("bound_investigation_continuation") is None
            and kwargs.get("document_context") is None
        )
        if not eligible or planner is None:
            return await method(self, *args, **kwargs)
        utterance = str(kwargs["utterance"])
        task = asyncio.create_task(
            asyncio.to_thread(
                planner.start_speculative_form,
                utterance=utterance,
                prior_turns=kwargs["prior_turns"],
                principal=kwargs["principal"],
                purpose=self._purpose,
                locale=kwargs.get("locale", "en"),
                stored_reference_context=kwargs.get("stored_reference_context"),
            )
        )
        speculation = SpeculativeForm(utterance, task)
        token = _CURRENT.set(speculation)
        try:
            return await method(self, *args, **kwargs)
        finally:
            _CURRENT.reset(token)
            speculation.release()

    return wrapper


__all__ = ["SpeculativeForm", "speculative_form_start", "take_speculative_form"]
