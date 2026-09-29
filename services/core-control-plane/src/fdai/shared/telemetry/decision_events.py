"""Turn-scoped capture of planner decision events for the local development channel.

The planner already emits structured, content-free decision events through standard logging,
such as judgment retries, rejected proposals, T2 escalation, grounding, and the selected plan
source. When the development diagnostic channel is enabled, this module binds one bounded
collector to each semantic turn and copies those events into it. The collector never leaves
the process; the development decision projection sanitizes it before any trace is retained.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock

from fdai_runtime_diagnostics.decisions import decision_traces_enabled

_MAX_EVENTS = 48
_LOGGER_NAMES = ("fdai", "fdai_core_service")
_EVENT_PREFIXES = ("semantic_", "conversation_")
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", logging.INFO, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


@dataclass
class DecisionTurn:
    """In-process decision events and model observations of one semantic turn."""

    events: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)
    observations: tuple[object, ...] = ()
    dropped_events: int = 0
    recorded: bool = False
    lock: Lock = field(default_factory=Lock, repr=False)


_TURN: ContextVar[DecisionTurn | None] = ContextVar("fdai_decision_turn", default=None)
_install_lock = Lock()
_installed: list[logging.Handler] = []


class _DecisionEventHandler(logging.Handler):
    """Copy structured conversation decision events into the bound turn collector."""

    def emit(self, record: logging.LogRecord) -> None:
        turn = _TURN.get()
        if turn is None or not isinstance(record.msg, str):
            return
        name = record.msg.split(" ", 1)[0]
        if not name.startswith(_EVENT_PREFIXES):
            return
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS
        }
        with turn.lock:
            if len(turn.events) < _MAX_EVENTS:
                turn.events.append((name, extras))
            else:
                turn.dropped_events += 1


def _install_handler() -> None:
    with _install_lock:
        if _installed:
            return
        handler = _DecisionEventHandler(level=logging.INFO)
        for name in _LOGGER_NAMES:
            logging.getLogger(name).addHandler(handler)
        _installed.append(handler)


@contextmanager
def bind_decision_events() -> Iterator[DecisionTurn | None]:
    """Bind one decision collector to the current semantic turn when diagnostics are enabled."""

    if not decision_traces_enabled():
        yield None
        return
    _install_handler()
    turn = DecisionTurn()
    token = _TURN.set(turn)
    try:
        yield turn
    finally:
        _TURN.reset(token)


def record_decision_observations(observations: Sequence[object]) -> None:
    """Attach the turn's model-call observations to the bound collector."""

    turn = _TURN.get()
    if turn is not None:
        turn.observations = tuple(observations)


def current_decision_turn() -> DecisionTurn | None:
    """Return the collector bound to the current semantic turn, if any."""

    return _TURN.get()


__all__ = [
    "DecisionTurn",
    "bind_decision_events",
    "current_decision_turn",
    "record_decision_observations",
]
