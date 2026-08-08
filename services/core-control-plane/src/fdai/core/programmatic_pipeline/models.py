"""Immutable public contracts for bounded programmatic tool pipelines."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_BOUNDED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


class ProgrammaticPipelineStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class ProgrammaticPipelineLimits:
    timeout_seconds: float = 30.0
    max_input_items: int = 64
    max_input_bytes: int = 256_000
    max_tool_calls: int = 32
    max_call_input_bytes: int = 64_000
    max_call_output_bytes: int = 256_000
    max_stdout_bytes: int = 16_000
    max_stderr_bytes: int = 16_000
    max_final_json_bytes: int = 256_000

    def __post_init__(self) -> None:
        if not 0.1 <= self.timeout_seconds <= 300:
            raise ValueError("pipeline timeout_seconds MUST be in [0.1, 300]")
        for name, value, maximum in (
            ("max_input_items", self.max_input_items, 1_000),
            ("max_input_bytes", self.max_input_bytes, 5_000_000),
            ("max_tool_calls", self.max_tool_calls, 128),
            ("max_call_input_bytes", self.max_call_input_bytes, 1_000_000),
            ("max_call_output_bytes", self.max_call_output_bytes, 5_000_000),
            ("max_stdout_bytes", self.max_stdout_bytes, 1_000_000),
            ("max_stderr_bytes", self.max_stderr_bytes, 1_000_000),
            ("max_final_json_bytes", self.max_final_json_bytes, 5_000_000),
        ):
            if not 1 <= value <= maximum:
                raise ValueError(f"{name} MUST be in [1, {maximum}]")


@dataclass(frozen=True, slots=True)
class ProgrammaticToolPipelineRequest:
    run_id: str
    reviewed_source: str
    reviewed_source_digest: str
    idempotency_key: str
    input_json: tuple[str, ...]
    allowed_read_tools: frozenset[str]
    sandbox_profile_id: str
    limits: ProgrammaticPipelineLimits

    def __post_init__(self) -> None:
        for name, value in (
            ("run_id", self.run_id),
            ("idempotency_key", self.idempotency_key),
            ("sandbox_profile_id", self.sandbox_profile_id),
        ):
            if _BOUNDED_ID.fullmatch(value) is None:
                raise ValueError(f"{name} MUST be a bounded identifier")
        if _DIGEST.fullmatch(self.reviewed_source_digest) is None:
            raise ValueError("reviewed_source_digest MUST be a SHA-256 digest")
        if not self.reviewed_source.strip() or len(self.reviewed_source.encode("utf-8")) > 256_000:
            raise ValueError("reviewed_source MUST be non-empty and <= 256000 bytes")
        if not self.allowed_read_tools or len(self.allowed_read_tools) > 64:
            raise ValueError("allowed_read_tools MUST contain [1, 64] tools")
        for tool_id in self.allowed_read_tools:
            if _BOUNDED_ID.fullmatch(tool_id) is None or "pipeline" in tool_id:
                raise ValueError("allowed_read_tools contains an invalid or recursive tool")
        if len(self.input_json) > self.limits.max_input_items:
            raise ValueError("pipeline input count exceeds its limit")
        total_bytes = sum(len(value.encode("utf-8")) for value in self.input_json)
        if total_bytes > self.limits.max_input_bytes:
            raise ValueError("pipeline input bytes exceed their limit")
        for value in self.input_json:
            try:
                json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("pipeline inputs MUST be valid JSON") from exc


class ProgrammaticCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProgrammaticPipelineCallReceipt:
    run_id: str
    call_id: str
    tool_id: str
    sequence: int
    status: ProgrammaticCallStatus
    input_digest: str
    output_digest: str | None
    receipt_ref: str
    started_at: datetime
    finished_at: datetime
    latency_ms: int
    input_bytes: int
    output_bytes: int
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("pipeline receipt timestamps MUST be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("pipeline receipt finished_at MUST be >= started_at")
        if self.sequence < 1 or min(self.latency_ms, self.input_bytes, self.output_bytes) < 0:
            raise ValueError("pipeline receipt counters MUST be non-negative")


@dataclass(frozen=True, slots=True)
class ProgrammaticPipelineStats:
    tool_calls: int
    succeeded_calls: int
    failed_calls: int
    input_bytes: int
    output_bytes: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ProgrammaticToolPipelineResult:
    run_id: str
    status: ProgrammaticPipelineStatus
    source_digest: str
    stdout: str
    stderr: str
    final_json: str | None
    receipt_refs: tuple[str, ...]
    stats: ProgrammaticPipelineStats
    complete: bool
    detail: str | None = None
    truncated: bool = False

    def compact_projection(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "complete": self.complete,
            "final": None if self.final_json is None else json.loads(self.final_json),
            "receipt_refs": list(self.receipt_refs),
            "stats": {
                "tool_calls": self.stats.tool_calls,
                "duration_ms": self.stats.duration_ms,
                "output_bytes": self.stats.output_bytes,
            },
            "truncated": self.truncated,
            "detail": self.detail,
        }


__all__ = [
    "ProgrammaticCallStatus",
    "ProgrammaticPipelineCallReceipt",
    "ProgrammaticPipelineLimits",
    "ProgrammaticPipelineStats",
    "ProgrammaticPipelineStatus",
    "ProgrammaticToolPipelineRequest",
    "ProgrammaticToolPipelineResult",
]
