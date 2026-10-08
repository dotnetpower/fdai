"""Relay best-effort semantic progress to active streams until the terminal replay arrives."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from collections.abc import Mapping

from fdai_service_contracts import MAX_INTENT_GRAPH_GOALS, SemanticQueryProgress
from fdai_service_contracts.semantic_model_call_progress import (
    MAX_MODEL_CALL_UPDATES_PER_TURN,
    SemanticModelCallProgress,
)
from fdai_service_contracts.semantic_work_progress import SemanticWorkProgress

MAX_TRACKED_PROGRESS_REQUESTS = 256
MAX_PROGRESS_UPDATES_PER_REQUEST = MAX_INTENT_GRAPH_GOALS * 2
_LOGGER = logging.getLogger(__name__)


class SemanticProgressRelay:
    """Retain a bounded best-effort timeline until the terminal replay arrives.

    Node lifecycle updates share one bounded deque per request. The plan-time work progress pin
    has its own slot so a full node timeline can never evict it before a stream reads it.
    """

    def __init__(self) -> None:
        self._updates: OrderedDict[str, deque[SemanticQueryProgress]] = OrderedDict()
        self._pins: OrderedDict[str, SemanticWorkProgress] = OrderedDict()
        # Planning model calls keep their own bounded slot so they never evict node progress.
        self._model_calls: OrderedDict[str, deque[SemanticModelCallProgress]] = OrderedDict()
        self._signals: dict[str, asyncio.Event] = {}
        self._terminals: OrderedDict[str, None] = OrderedDict()

    def terminal_committed(self, request_id: str) -> None:
        """Wake readers only after terminal validation and durable persistence succeed."""
        self._terminals[request_id] = None
        self._terminals.move_to_end(request_id)
        if len(self._terminals) > MAX_TRACKED_PROGRESS_REQUESTS:
            self._terminals.popitem(last=False)
            _LOGGER.warning(
                "semantic_progress_capacity_evicted",
                extra={"kind": "terminal", "capacity": MAX_TRACKED_PROGRESS_REQUESTS},
            )
        signal = self._signals.get(request_id)
        if signal is not None:
            signal.set()

    def consume(self, payload: Mapping[str, object]) -> bool:
        """Validate and retain one monotonic update, ignoring stale redelivery."""
        if payload.get("record_kind") == "work_progress_shape":
            pin = SemanticWorkProgress.model_validate(payload)
            if pin.request_id in self._pins:
                return False
            self._pins[pin.request_id] = pin
            if len(self._pins) > MAX_TRACKED_PROGRESS_REQUESTS:
                self._pins.popitem(last=False)
                _LOGGER.warning(
                    "semantic_progress_capacity_evicted",
                    extra={"kind": "pin", "capacity": MAX_TRACKED_PROGRESS_REQUESTS},
                )
            self._signal(pin.request_id)
            return True
        if payload.get("record_kind") == "model_call_progress":
            return self._consume_model_call(SemanticModelCallProgress.model_validate(payload))
        progress = SemanticQueryProgress.model_validate(payload)
        updates = self._updates.get(progress.request_id)
        if updates is None:
            if len(self._updates) >= MAX_TRACKED_PROGRESS_REQUESTS:
                expired_request_id, _expired = self._updates.popitem(last=False)
                self._signals.pop(expired_request_id, None)
                self._pins.pop(expired_request_id, None)
                _LOGGER.warning(
                    "semantic_progress_capacity_evicted",
                    extra={"kind": "progress", "capacity": MAX_TRACKED_PROGRESS_REQUESTS},
                )
            updates = deque(maxlen=MAX_PROGRESS_UPDATES_PER_REQUEST)
            self._updates[progress.request_id] = updates
        elif updates and progress.progress_sequence <= updates[-1].progress_sequence:
            return False
        updates.append(progress)
        self._signal(progress.request_id)
        self._updates.move_to_end(progress.request_id)
        return True

    def _consume_model_call(self, call: SemanticModelCallProgress) -> bool:
        calls = self._model_calls.get(call.request_id)
        if calls is None:
            if len(self._model_calls) >= MAX_TRACKED_PROGRESS_REQUESTS:
                self._model_calls.popitem(last=False)
                _LOGGER.warning(
                    "semantic_progress_capacity_evicted",
                    extra={"kind": "model_call", "capacity": MAX_TRACKED_PROGRESS_REQUESTS},
                )
            calls = deque(maxlen=MAX_MODEL_CALL_UPDATES_PER_TURN)
            self._model_calls[call.request_id] = calls
        elif calls and call.progress_sequence <= calls[-1].progress_sequence:
            return False
        calls.append(call)
        self._model_calls.move_to_end(call.request_id)
        self._signal(call.request_id)
        return True

    def model_calls_after(
        self, request_id: str, progress_sequence: int
    ) -> tuple[SemanticModelCallProgress, ...]:
        """Return retained planning model-call updates after one stream cursor."""
        return tuple(
            call
            for call in self._model_calls.get(request_id, ())
            if call.progress_sequence > progress_sequence
        )

    def pin(self, request_id: str) -> SemanticWorkProgress | None:
        """Return the plan-time pin published for one request, if it arrived."""
        return self._pins.get(request_id)

    def after(self, request_id: str, progress_sequence: int) -> tuple[SemanticQueryProgress, ...]:
        """Return retained updates after one iterator-local sequence cursor."""
        return tuple(
            update
            for update in self._updates.get(request_id, ())
            if update.progress_sequence > progress_sequence
        )

    def discard(self, request_id: str) -> None:
        """Drop transient updates once durable terminal replay is authoritative."""
        self._updates.pop(request_id, None)
        self._model_calls.pop(request_id, None)
        self._pins.pop(request_id, None)
        self._signals.pop(request_id, None)
        self._terminals.pop(request_id, None)

    async def wait_for_update(
        self,
        request_id: str,
        progress_sequence: int,
        *,
        timeout: float,
        pin_pending: bool = False,
    ) -> None:
        """Wake one active stream as soon as a newer update or an unread pin arrives."""
        if self._ready(request_id, progress_sequence, pin_pending=pin_pending):
            return
        signal = self._signals.setdefault(request_id, asyncio.Event())
        signal.clear()
        if self._ready(request_id, progress_sequence, pin_pending=pin_pending):
            return
        try:
            await asyncio.wait_for(signal.wait(), timeout=timeout)
        except TimeoutError:
            return

    def _ready(self, request_id: str, progress_sequence: int, *, pin_pending: bool) -> bool:
        return (
            request_id in self._terminals
            or bool(self.after(request_id, progress_sequence))
            or bool(self.model_calls_after(request_id, progress_sequence))
            or (pin_pending and request_id in self._pins)
        )

    def _signal(self, request_id: str) -> None:
        self._signals.setdefault(request_id, asyncio.Event()).set()


__all__ = [
    "MAX_PROGRESS_UPDATES_PER_REQUEST",
    "MAX_TRACKED_PROGRESS_REQUESTS",
    "SemanticProgressRelay",
]
