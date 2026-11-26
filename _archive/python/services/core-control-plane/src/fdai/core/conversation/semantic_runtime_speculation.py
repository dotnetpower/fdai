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
from dataclasses import is_dataclass, replace
from typing import Any, Concatenate, Protocol, cast

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
            return await asyncio.shield(self._task)
        except asyncio.CancelledError:
            self._cancel_when_done()
            raise
        except Exception:  # noqa: BLE001 - a failed speculation falls back to the normal start
            _LOGGER.warning("semantic_speculative_form_unavailable")
            return None

    async def release(self) -> tuple[Any, ...]:
        """Await, cancel, and drain an unadopted speculative ticket before returning the turn."""

        if self._taken:
            return ()
        self._taken = True
        try:
            ticket = await asyncio.shield(self._task)
        except asyncio.CancelledError:
            self._cancel_when_done()
            raise
        except Exception:  # noqa: BLE001 - failed speculation has no ticket to drain
            _LOGGER.warning("semantic_speculative_form_unavailable")
            return ()
        if ticket is None:
            return ()
        ticket.cancel()
        return tuple(getattr(ticket, "observations", ()))

    def abort(self) -> None:
        """Cancel an unadopted ticket when the turn exits with an exception."""

        if self._taken:
            return
        self._taken = True
        self._cancel_when_done()

    def _cancel_when_done(self) -> None:
        def cancel(task: asyncio.Task[CompiledAnswerTicket | None]) -> None:
            if not task.cancelled() and task.exception() is None:
                ticket = task.result()
                if ticket is not None:
                    ticket.cancel()

        if self._task.done():
            cancel(self._task)
        else:
            self._task.add_done_callback(cancel)


def _attach_unadopted_observations[R](result: R, observations: tuple[Any, ...]) -> R:
    """Append observations from a cancelled unadopted speculative ticket onto the turn result."""

    if not observations or not is_dataclass(result):
        return result
    planning = getattr(result, "planning", None)
    if planning is None or not is_dataclass(planning):
        return result
    current = getattr(planning, "model_observations", None)
    if not isinstance(current, tuple):
        return result
    existing = {id(item) for item in current}
    merged = (*current, *(item for item in observations if id(item) not in existing))
    if len(merged) == len(current):
        return result
    updated_planning = replace(cast(Any, planning), model_observations=merged)
    return cast(R, replace(cast(Any, result), planning=updated_planning))


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
            result = await method(self, *args, **kwargs)
            unadopted = await speculation.release()
            return _attach_unadopted_observations(result, unadopted)
        finally:
            _CURRENT.reset(token)
            speculation.abort()

    return wrapper


__all__ = ["SpeculativeForm", "speculative_form_start", "take_speculative_form"]
