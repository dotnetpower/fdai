"""Deterministic comparison with sequential model-mediated tool calls."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProgrammaticPipelineBenchmark:
    tool_calls: int
    sequential_context_bytes: int
    compact_context_bytes: int
    sequential_estimated_ms: int
    programmatic_estimated_ms: int

    @property
    def context_reduction_ratio(self) -> float:
        if self.sequential_context_bytes == 0:
            return 0.0
        return 1 - (self.compact_context_bytes / self.sequential_context_bytes)

    @property
    def latency_reduction_ratio(self) -> float:
        if self.sequential_estimated_ms == 0:
            return 0.0
        return 1 - (self.programmatic_estimated_ms / self.sequential_estimated_ms)


def benchmark_programmatic_pipeline(
    *,
    sequential_turns: tuple[dict[str, object], ...],
    compact_projection: dict[str, object],
    model_roundtrip_ms: int,
    broker_roundtrip_ms: int,
) -> ProgrammaticPipelineBenchmark:
    if model_roundtrip_ms < 0 or broker_roundtrip_ms < 0:
        raise ValueError("benchmark roundtrip durations MUST be non-negative")
    sequential_bytes = sum(_json_bytes(turn) for turn in sequential_turns)
    compact_bytes = _json_bytes(compact_projection)
    calls = len(sequential_turns)
    return ProgrammaticPipelineBenchmark(
        tool_calls=calls,
        sequential_context_bytes=sequential_bytes,
        compact_context_bytes=compact_bytes,
        sequential_estimated_ms=calls * (model_roundtrip_ms + broker_roundtrip_ms),
        programmatic_estimated_ms=model_roundtrip_ms + calls * broker_roundtrip_ms,
    )


def _json_bytes(value: dict[str, object]) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


__all__ = ["ProgrammaticPipelineBenchmark", "benchmark_programmatic_pipeline"]
