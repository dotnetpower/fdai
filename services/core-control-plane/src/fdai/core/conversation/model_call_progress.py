"""Report each planning model call to an invocation-bound presentation observer.

The shared provider call gate reports when a reviewed call stage sends a request and when it
ends. A report names the stage, the deployment, the times, and the outcome; it never carries a
prompt, a response, or question text, and it grants no authority. Reporting is best effort: the
observer runs on the loop that bound it, never blocks the call, and its failures are dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .turn_reservations import CALL_STAGES

MAX_REPORTED_MODEL_CALLS = 32
_LOGGER = logging.getLogger(__name__)

ModelCallStatus = Literal["running", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class ModelCallProgress:
    """One start or end of a planning model call."""

    call_index: int
    stage: str
    status: ModelCallStatus
    model: str | None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None


ModelCallProgressObserver = Callable[[ModelCallProgress], None]


class _Binding:
    def __init__(
        self, observer: ModelCallProgressObserver, loop: asyncio.AbstractEventLoop
    ) -> None:
        self.observer = observer
        self.loop = loop
        self.lock = threading.Lock()
        self.calls = 0


@dataclass(frozen=True, slots=True)
class ModelCallHandle:
    """The start of one reported call, so its end reports against the same index."""

    binding: _Binding
    call_index: int
    stage: str
    model: str | None
    started_at: datetime
    started: float


_BINDING: ContextVar[_Binding | None] = ContextVar("model_call_progress", default=None)


@contextmanager
def bind_model_call_progress_observer(observer: ModelCallProgressObserver) -> Iterator[None]:
    """Bind one observer to the model calls made in this context and its child tasks."""

    token = _BINDING.set(_Binding(observer, asyncio.get_running_loop()))
    try:
        yield
    finally:
        _BINDING.reset(token)


def model_call_started(label: str | None, model: str | None) -> ModelCallHandle | None:
    """Report the start of one reviewed-stage call, or return ``None`` when nothing observes it."""

    binding = _BINDING.get()
    stage = CALL_STAGES.get(label or "")
    if binding is None or stage is None:
        return None
    with binding.lock:
        if binding.calls >= MAX_REPORTED_MODEL_CALLS:
            return None
        binding.calls += 1
        call_index = binding.calls
    handle = ModelCallHandle(
        binding, call_index, stage.value, model, datetime.now(UTC), time.monotonic()
    )
    _report(
        binding,
        ModelCallProgress(call_index, handle.stage, "running", model, handle.started_at),
    )
    return handle


def model_call_ended(handle: ModelCallHandle | None, *, failed: bool) -> None:
    """Report how one started call ended."""

    if handle is None:
        return
    _report(
        handle.binding,
        ModelCallProgress(
            handle.call_index,
            handle.stage,
            "failed" if failed else "completed",
            handle.model,
            handle.started_at,
            completed_at=datetime.now(UTC),
            duration_ms=max(0, int((time.monotonic() - handle.started) * 1000)),
        ),
    )


def _report(binding: _Binding, progress: ModelCallProgress) -> None:
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if running is binding.loop:
            binding.observer(progress)
        elif not binding.loop.is_closed():
            binding.loop.call_soon_threadsafe(_deliver, binding.observer, progress)
    except Exception:  # noqa: BLE001 - presentation progress never affects the call it observes
        _LOGGER.debug("model_call_progress_report_dropped", exc_info=True)


def _deliver(observer: ModelCallProgressObserver, progress: ModelCallProgress) -> None:
    with contextlib.suppress(Exception):
        observer(progress)


__all__ = [
    "MAX_REPORTED_MODEL_CALLS",
    "ModelCallHandle",
    "ModelCallProgress",
    "ModelCallProgressObserver",
    "bind_model_call_progress_observer",
    "model_call_ended",
    "model_call_started",
]
