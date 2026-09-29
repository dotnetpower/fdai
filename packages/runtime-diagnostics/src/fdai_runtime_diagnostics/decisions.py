"""Bounded content-free semantic decision traces for local development review."""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from pydantic import ValidationError

from fdai_runtime_diagnostics.models import DecisionTrace

_MAX_TRACES = 50
# Fifty traces stay well inside the one-MiB socket response bound.
_MAX_TRACE_BYTES = 16_000
_LOCK_TIMEOUT_SECONDS = 0.01


@dataclass(frozen=True)
class DecisionSnapshot:
    """Retained traces, oldest first, cumulative loss counters, and recent rejections."""

    traces: tuple[DecisionTrace, ...]
    evicted: int
    rejected: int
    recent_rejections: int


_traces: deque[DecisionTrace] = deque(maxlen=_MAX_TRACES)
# One flag per recent recording attempt, so a snapshot can report recent loss without state.
_attempts: deque[bool] = deque(maxlen=_MAX_TRACES)
_lock = Lock()
_state = {"sequence": 0, "evicted": 0, "rejected": 0}


def decision_traces_enabled() -> bool:
    """Return whether this process records decision traces for the local channel."""
    return os.environ.get("FDAI_DEVELOPMENT_DIAGNOSTICS", "").strip().lower() in {"1", "true"}


def observe_decision(
    *,
    session: str,
    turn_sequence: int | None,
    steps: Sequence[Mapping[str, object]],
    cues: Sequence[Mapping[str, object]] = (),
) -> bool:
    """Retain one validated trace as bounded best effort.

    The caller is a product turn, so this function never raises and waits at most ten
    milliseconds for the buffer lock. A trace that fails the contract is counted as rejected.
    """
    if not decision_traces_enabled():
        return False
    try:
        acquired = _lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS)
    except (RuntimeError, ValueError):
        return False
    if not acquired:
        return False
    try:
        try:
            trace: DecisionTrace | None = DecisionTrace.model_validate(
                {
                    "sequence": _state["sequence"] + 1,
                    "recorded_at": datetime.now(UTC),
                    "session": session,
                    "turn_sequence": turn_sequence,
                    "steps": tuple(steps),
                    "cues": tuple(cues),
                }
            )
        except (ValidationError, TypeError, ValueError):
            trace = None
        if trace is None or len(trace.model_dump_json()) > _MAX_TRACE_BYTES:
            _state["rejected"] += 1
            _attempts.append(False)
            return False
        _attempts.append(True)
        _state["sequence"] += 1
        if len(_traces) == _MAX_TRACES:
            _state["evicted"] += 1
        _traces.append(trace)
        return True
    finally:
        _lock.release()


def decision_snapshot() -> DecisionSnapshot:
    """Return retained traces and rejections among the last 50 attempts, without side effects."""
    if not decision_traces_enabled():
        return DecisionSnapshot((), 0, 0, 0)
    with _lock:
        return DecisionSnapshot(
            tuple(_traces),
            _state["evicted"],
            _state["rejected"],
            sum(1 for accepted in _attempts if not accepted),
        )


def reset_decision_traces() -> None:
    """Clear retained traces; used by tests and never by the product path."""
    with _lock:
        _traces.clear()
        _attempts.clear()
        for key in _state:
            _state[key] = 0


__all__ = [
    "DecisionSnapshot",
    "decision_snapshot",
    "decision_traces_enabled",
    "observe_decision",
    "reset_decision_traces",
]
