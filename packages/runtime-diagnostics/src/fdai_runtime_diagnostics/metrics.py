"""Bounded process-local stage latency aggregates."""

from __future__ import annotations

import math
import os
import re
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from fdai_runtime_diagnostics.models import StageLatency

_NAME = re.compile(r"^[a-z0-9._-]{1,128}$")
_MAX_SAMPLES = 1000
_samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))
_lock = Lock()


def observe_stage(name: str, duration_ms: float) -> None:
    """Record one content-free stage duration in a bounded rolling window."""
    if os.environ.get("FDAI_DEVELOPMENT_DIAGNOSTICS", "").strip().lower() not in {
        "1",
        "true",
    }:
        return
    if _NAME.fullmatch(name) is None:
        raise ValueError("development diagnostic stage name is invalid")
    if isinstance(duration_ms, bool) or not math.isfinite(duration_ms) or duration_ms < 0:
        raise ValueError("development diagnostic duration MUST be finite and non-negative")
    with _lock:
        _samples[name].append(float(duration_ms))


@contextmanager
def stage_timer(name: str) -> Iterator[None]:
    """Measure one synchronous or async-call-site stage with a monotonic clock."""
    started = time.monotonic_ns()
    try:
        yield
    finally:
        observe_stage(name, (time.monotonic_ns() - started) / 1_000_000)


def stage_snapshot() -> tuple[StageLatency, ...]:
    """Return deterministic percentile summaries without exposing request content."""
    if os.environ.get("FDAI_DEVELOPMENT_DIAGNOSTICS", "").strip().lower() not in {
        "1",
        "true",
    }:
        return ()
    with _lock:
        copied = {name: tuple(values) for name, values in _samples.items() if values}
    return tuple(_summary(name, values) for name, values in sorted(copied.items()))


def _summary(name: str, values: tuple[float, ...]) -> StageLatency:
    ordered = tuple(sorted(values))
    return StageLatency(
        name=name,
        count=len(ordered),
        p50_ms=round(_percentile(ordered, 0.50), 3),
        p95_ms=round(_percentile(ordered, 0.95), 3),
        p99_ms=round(_percentile(ordered, 0.99), 3),
        max_ms=round(ordered[-1], 3),
    )


def _percentile(values: tuple[float, ...], fraction: float) -> float:
    index = max(0, math.ceil(len(values) * fraction) - 1)
    return values[min(index, len(values) - 1)]


__all__ = ["observe_stage", "stage_snapshot", "stage_timer"]
