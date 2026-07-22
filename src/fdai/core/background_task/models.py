"""Bounded contracts for durable detached background investigations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_MAX_ID = 256
_MAX_PROMPT = 4_000
_MAX_PROGRESS = 1_000


class BackgroundTaskKind(StrEnum):
    READ_ONLY_INVESTIGATION = "read_only_investigation"


class BackgroundTaskStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"


TERMINAL_BACKGROUND_STATUSES = frozenset(
    {
        BackgroundTaskStatus.SUCCEEDED,
        BackgroundTaskStatus.FAILED,
        BackgroundTaskStatus.CANCELLED,
        BackgroundTaskStatus.TIMED_OUT,
        BackgroundTaskStatus.UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class BackgroundTaskOrigin:
    conversation_id: str
    channel_kind: str
    channel_id: str
    thread_id: str | None = None
    message_id: str | None = None

    def __post_init__(self) -> None:
        _id("conversation_id", self.conversation_id)
        _id("channel_kind", self.channel_kind)
        _id("channel_id", self.channel_id)
        if self.thread_id is not None:
            _id("thread_id", self.thread_id)
        if self.message_id is not None:
            _id("message_id", self.message_id)


@dataclass(frozen=True, slots=True)
class BackgroundTaskBudget:
    max_wall_seconds: int = 300
    max_tokens: int = 4_096
    max_cost_microusd: int = 500_000
    max_tool_calls: int = 5
    max_progress_events: int = 32

    def __post_init__(self) -> None:
        if not 1 <= self.max_wall_seconds <= 3_600:
            raise ValueError("max_wall_seconds MUST be in [1, 3600]")
        if not 1 <= self.max_tokens <= 32_768:
            raise ValueError("max_tokens MUST be in [1, 32768]")
        if not 0 <= self.max_cost_microusd <= 10_000_000:
            raise ValueError("max_cost_microusd MUST be in [0, 10000000]")
        if not 0 <= self.max_tool_calls <= 100:
            raise ValueError("max_tool_calls MUST be in [0, 100]")
        if not 1 <= self.max_progress_events <= 256:
            raise ValueError("max_progress_events MUST be in [1, 256]")


@dataclass(frozen=True, slots=True)
class BackgroundTask:
    task_id: str
    owner_principal_id: str
    origin: BackgroundTaskOrigin
    kind: BackgroundTaskKind
    prompt: str
    context_digest: str
    capability_profile_id: str
    budget: BackgroundTaskBudget
    correlation_id: str
    idempotency_key: str
    created_at: datetime
    retention_until: datetime
    retryable: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("task_id", self.task_id),
            ("owner_principal_id", self.owner_principal_id),
            ("context_digest", self.context_digest),
            ("capability_profile_id", self.capability_profile_id),
            ("correlation_id", self.correlation_id),
            ("idempotency_key", self.idempotency_key),
        ):
            _id(name, value)
        _text("prompt", self.prompt, _MAX_PROMPT)
        _aware("created_at", self.created_at)
        _aware("retention_until", self.retention_until)
        if self.retention_until <= self.created_at:
            raise ValueError("retention_until MUST be after created_at")
        if self.kind is not BackgroundTaskKind.READ_ONLY_INVESTIGATION:
            raise ValueError("only read_only_investigation is supported")
        if self.capability_profile_id != "background.read-only":
            raise ValueError("background tasks require the background.read-only profile")


@dataclass(frozen=True, slots=True)
class BackgroundTaskLease:
    owner: str
    token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        _id("lease owner", self.owner)
        _id("lease token", self.token)
        _aware("lease expires_at", self.expires_at)


@dataclass(frozen=True, slots=True)
class BackgroundTaskUsage:
    tokens: int = 0
    cost_microusd: int = 0
    tool_calls: int = 0

    def __post_init__(self) -> None:
        if self.tokens < 0 or self.cost_microusd < 0 or self.tool_calls < 0:
            raise ValueError("background task usage MUST be non-negative")


@dataclass(frozen=True, slots=True)
class BackgroundTaskResult:
    summary: str | None
    evidence_refs: tuple[str, ...]
    terminal_reason: str
    usage: BackgroundTaskUsage
    started_at: datetime
    finished_at: datetime
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.summary is not None:
            _text("result summary", self.summary, 8_000)
        for ref in self.evidence_refs:
            _id("evidence_ref", ref)
        if len(self.evidence_refs) > 64 or len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs MUST contain <= 64 unique values")
        _id("terminal_reason", self.terminal_reason)
        _aware("started_at", self.started_at)
        _aware("finished_at", self.finished_at)
        if self.finished_at < self.started_at:
            raise ValueError("finished_at MUST be >= started_at")
        if self.trusted:
            raise ValueError("background task results MUST remain untrusted")


@dataclass(frozen=True, slots=True)
class BackgroundTaskAttempt:
    attempt_id: str
    task: BackgroundTask
    attempt_number: int
    status: BackgroundTaskStatus
    revision: int
    updated_at: datetime
    lease: BackgroundTaskLease | None = None
    usage: BackgroundTaskUsage = BackgroundTaskUsage()
    result: BackgroundTaskResult | None = None
    parent_attempt_id: str | None = None

    def __post_init__(self) -> None:
        _id("attempt_id", self.attempt_id)
        if self.parent_attempt_id is not None:
            _id("parent_attempt_id", self.parent_attempt_id)
        if self.attempt_number < 1 or self.revision < 1:
            raise ValueError("attempt_number and revision MUST be positive")
        _aware("updated_at", self.updated_at)
        if self.status in {BackgroundTaskStatus.CLAIMED, BackgroundTaskStatus.RUNNING}:
            if self.lease is None or self.result is not None:
                raise ValueError("claimed/running attempts require a lease and no result")
        elif self.status is BackgroundTaskStatus.QUEUED:
            if self.lease is not None or self.result is not None:
                raise ValueError("queued attempts cannot have a lease or result")
        elif self.status in TERMINAL_BACKGROUND_STATUSES:
            if self.lease is not None or self.result is None:
                raise ValueError("terminal attempts require a result and no lease")
        else:  # pragma: no cover - exhaustive enum guard
            raise ValueError("unsupported background task status")


@dataclass(frozen=True, slots=True)
class BackgroundTaskProgress:
    attempt_id: str
    sequence: int
    kind: str
    message: str
    at: datetime
    usage: BackgroundTaskUsage

    def __post_init__(self) -> None:
        _id("attempt_id", self.attempt_id)
        _id("progress kind", self.kind)
        _text("progress message", self.message, _MAX_PROGRESS)
        _aware("progress at", self.at)
        if self.sequence < 0:
            raise ValueError("progress sequence MUST be non-negative")


def _id(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_ID or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _text(name: str, value: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be bounded text")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "TERMINAL_BACKGROUND_STATUSES",
    "BackgroundTask",
    "BackgroundTaskAttempt",
    "BackgroundTaskBudget",
    "BackgroundTaskKind",
    "BackgroundTaskLease",
    "BackgroundTaskOrigin",
    "BackgroundTaskProgress",
    "BackgroundTaskResult",
    "BackgroundTaskStatus",
    "BackgroundTaskUsage",
]
