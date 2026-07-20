"""Data contracts for isolated, ephemeral investigation workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_MAX_TEXT = 2_000
_MAX_SUMMARY = 8_000
_MAX_ITEMS = 64


class TaskWorkerStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    ABSTAINED = "abstained"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DENIED = "denied"
    FAILED = "failed"


TERMINAL_WORKER_STATUSES = frozenset(
    {
        TaskWorkerStatus.SUCCEEDED,
        TaskWorkerStatus.ABSTAINED,
        TaskWorkerStatus.CANCELLED,
        TaskWorkerStatus.TIMED_OUT,
        TaskWorkerStatus.BUDGET_EXHAUSTED,
        TaskWorkerStatus.DENIED,
        TaskWorkerStatus.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class TaskWorkerBudget:
    max_wall_seconds: float = 30.0
    max_tool_calls: int = 8
    max_tokens: int = 4_096
    max_cost_microusd: int = 500_000
    heartbeat_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 0.1 <= self.max_wall_seconds <= 300:
            raise ValueError("max_wall_seconds MUST be in [0.1, 300]")
        if not 0 <= self.max_tool_calls <= 32:
            raise ValueError("max_tool_calls MUST be in [0, 32]")
        if not 1 <= self.max_tokens <= 32_768:
            raise ValueError("max_tokens MUST be in [1, 32768]")
        if not 0 <= self.max_cost_microusd <= 10_000_000:
            raise ValueError("max_cost_microusd MUST be in [0, 10000000]")
        if not 0.05 <= self.heartbeat_seconds <= self.max_wall_seconds:
            raise ValueError("heartbeat_seconds MUST be in [0.05, max_wall_seconds]")


@dataclass(frozen=True, slots=True)
class AttenuatedCapabilities:
    allowed_tools: frozenset[str]
    denied_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.allowed_tools) > 64 or len(self.denied_tools) > 64:
            raise ValueError("worker capability count exceeds 64")
        for value in (*self.allowed_tools, *self.denied_tools):
            _bounded_id("worker tool", value)
        if self.allowed_tools.intersection(self.denied_tools):
            raise ValueError("allowed and denied worker tools MUST be disjoint")


@dataclass(frozen=True, slots=True)
class TaskWorkerRequest:
    worker_id: str
    parent_trace_ref: str
    cancellation_owner: str
    goal: str
    evidence_refs: tuple[str, ...]
    constraints: tuple[str, ...]
    requested_tools: frozenset[str]
    budget: TaskWorkerBudget
    created_at: datetime
    depth: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("worker_id", self.worker_id),
            ("parent_trace_ref", self.parent_trace_ref),
            ("cancellation_owner", self.cancellation_owner),
        ):
            _bounded_id(name, value)
        _bounded_text("goal", self.goal, maximum=_MAX_TEXT)
        _bounded_tuple("evidence_refs", self.evidence_refs, maximum=_MAX_ITEMS)
        _bounded_tuple("constraints", self.constraints, maximum=16)
        if len(self.requested_tools) > 64:
            raise ValueError("requested_tools exceeds 64")
        for ref in self.evidence_refs:
            _bounded_id("evidence_ref", ref)
        for constraint in self.constraints:
            _bounded_text("constraint", constraint, maximum=1_000)
        for tool in self.requested_tools:
            _bounded_id("requested_tool", tool)
        if self.created_at.tzinfo is None:
            raise ValueError("created_at MUST be timezone-aware")
        if self.depth != 1:
            raise ValueError("task workers support depth 1 only")


@dataclass(frozen=True, slots=True)
class TaskWorkerContext:
    goal: str
    evidence_refs: tuple[str, ...]
    constraints: tuple[str, ...]
    parent_trace_ref: str


@dataclass(frozen=True, slots=True)
class TaskWorkerUsage:
    tokens: int = 0
    cost_microusd: int = 0
    tool_calls: int = 0

    def __post_init__(self) -> None:
        if self.tokens < 0 or self.cost_microusd < 0 or self.tool_calls < 0:
            raise ValueError("worker usage values MUST be non-negative")

    def within(self, budget: TaskWorkerBudget) -> bool:
        return (
            self.tokens <= budget.max_tokens
            and self.cost_microusd <= budget.max_cost_microusd
            and self.tool_calls <= budget.max_tool_calls
        )


@dataclass(frozen=True, slots=True)
class TaskWorkerOutput:
    summary: str
    evidence_refs: tuple[str, ...]
    caveats: tuple[str, ...]
    usage: TaskWorkerUsage
    abstained: bool = False

    def __post_init__(self) -> None:
        _bounded_text("summary", self.summary, maximum=_MAX_SUMMARY)
        _bounded_tuple("evidence_refs", self.evidence_refs, maximum=_MAX_ITEMS)
        _bounded_tuple("caveats", self.caveats, maximum=16)
        for ref in self.evidence_refs:
            _bounded_id("evidence_ref", ref)
        for caveat in self.caveats:
            _bounded_text("caveat", caveat, maximum=1_000)


@dataclass(frozen=True, slots=True)
class TaskWorkerToolResult:
    data: tuple[tuple[str, str], ...]
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.data) > 64:
            raise ValueError("worker tool data exceeds 64 fields")
        for key, value in self.data:
            _bounded_id("worker tool data key", key)
            _bounded_text("worker tool data value", value, maximum=2_000)
        _bounded_tuple("evidence_refs", self.evidence_refs, maximum=_MAX_ITEMS)
        for ref in self.evidence_refs:
            _bounded_id("evidence_ref", ref)


@dataclass(frozen=True, slots=True)
class TaskWorkerResult:
    worker_id: str
    parent_trace_ref: str
    status: TaskWorkerStatus
    summary: str | None
    evidence_refs: tuple[str, ...]
    caveats: tuple[str, ...]
    usage: TaskWorkerUsage
    terminal_reason: str
    started_at: datetime
    finished_at: datetime
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_WORKER_STATUSES:
            raise ValueError("TaskWorkerResult status MUST be terminal")
        _bounded_id("worker_id", self.worker_id)
        _bounded_id("parent_trace_ref", self.parent_trace_ref)
        _bounded_id("terminal_reason", self.terminal_reason)
        if self.summary is not None:
            _bounded_text("summary", self.summary, maximum=_MAX_SUMMARY)
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("worker result timestamps MUST be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at MUST be >= started_at")
        if self.trusted:
            raise ValueError("task worker results MUST remain untrusted")


@dataclass(frozen=True, slots=True)
class TaskWorkerSnapshot:
    request: TaskWorkerRequest
    capabilities: AttenuatedCapabilities
    status: TaskWorkerStatus
    usage: TaskWorkerUsage
    updated_at: datetime
    heartbeat_at: datetime | None = None
    result: TaskWorkerResult | None = None

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise ValueError("worker snapshot updated_at MUST be timezone-aware")
        if self.heartbeat_at is not None and self.heartbeat_at.tzinfo is None:
            raise ValueError("worker heartbeat_at MUST be timezone-aware")
        if self.result is not None and self.result.worker_id != self.request.worker_id:
            raise ValueError("worker snapshot result id mismatch")


@dataclass(frozen=True, slots=True)
class TaskWorkerEvent:
    worker_id: str
    sequence: int
    kind: str
    at: datetime
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _bounded_id("worker_id", self.worker_id)
        _bounded_id("event kind", self.kind)
        if self.sequence < 0 or self.at.tzinfo is None:
            raise ValueError("worker event sequence/timestamp is invalid")
        if len(self.details) > 32:
            raise ValueError("worker event details exceed cap")
        for key, value in self.details:
            _bounded_id("event detail key", key)
            _bounded_text("event detail value", value, maximum=1_000)


def isolated_context(request: TaskWorkerRequest) -> TaskWorkerContext:
    """Project only explicitly allowed immutable request fields."""
    return TaskWorkerContext(
        goal=request.goal,
        evidence_refs=request.evidence_refs,
        constraints=request.constraints,
        parent_trace_ref=request.parent_trace_ref,
    )


def _bounded_id(name: str, value: str) -> None:
    if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _bounded_text(name: str, value: str, *, maximum: int) -> None:
    if not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be bounded text")


def _bounded_tuple(name: str, values: tuple[str, ...], *, maximum: int) -> None:
    if len(values) > maximum or len(set(values)) != len(values):
        raise ValueError(f"{name} MUST contain <= {maximum} unique values")


__all__ = [
    "TERMINAL_WORKER_STATUSES",
    "AttenuatedCapabilities",
    "TaskWorkerBudget",
    "TaskWorkerContext",
    "TaskWorkerEvent",
    "TaskWorkerOutput",
    "TaskWorkerRequest",
    "TaskWorkerResult",
    "TaskWorkerSnapshot",
    "TaskWorkerStatus",
    "TaskWorkerToolResult",
    "TaskWorkerUsage",
    "isolated_context",
]
