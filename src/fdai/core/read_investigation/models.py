"""Immutable request and plan contracts for bounded read investigations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.shared.providers.read_investigation import (
    ReadEvidenceEnvelope,
    ReadInvestigationIntent,
    ReadToolId,
    ResourceResolution,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallReceipt

_MAX_ID = 256


@dataclass(frozen=True, slots=True)
class ReadInvestigationBudget:
    max_wall_seconds: int = 60
    max_cost_microusd: int = 100_000
    max_tool_calls: int = 5
    max_results: int = 32
    max_output_bytes: int = 256_000

    def __post_init__(self) -> None:
        if not 1 <= self.max_wall_seconds <= 3_600:
            raise ValueError("max_wall_seconds MUST be in [1, 3600]")
        if not 0 <= self.max_cost_microusd <= 10_000_000:
            raise ValueError("max_cost_microusd MUST be in [0, 10000000]")
        if not 1 <= self.max_tool_calls <= 5:
            raise ValueError("max_tool_calls MUST be in [1, 5]")
        if not 2 <= self.max_results <= 64:
            raise ValueError("max_results MUST be in [2, 64]")
        if not 1_024 <= self.max_output_bytes <= 1_000_000:
            raise ValueError("max_output_bytes MUST be in [1024, 1000000]")


@dataclass(frozen=True, slots=True)
class ReadInvestigationRequest:
    requester_ref: str
    conversation_ref: str
    correlation_ref: str
    intent: ReadInvestigationIntent
    selector: ResourceSelector
    lookback_seconds: int
    requested_evidence: tuple[ReadToolId, ...]
    budget: ReadInvestigationBudget
    idempotency_key: str
    created_at: datetime
    explicit_deep: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("requester_ref", self.requester_ref),
            ("conversation_ref", self.conversation_ref),
            ("correlation_ref", self.correlation_ref),
            ("idempotency_key", self.idempotency_key),
        ):
            _identifier(name, value)
        if self.created_at.tzinfo is None:
            raise ValueError("created_at MUST be timezone-aware")
        if not 60 <= self.lookback_seconds <= 2_592_000:
            raise ValueError("lookback_seconds MUST be in [60, 2592000]")
        if ReadToolId.RESOLVE_RESOURCE in self.requested_evidence:
            raise ValueError("resolve_resource is server-owned and MUST NOT be requested")
        if len(set(self.requested_evidence)) != len(self.requested_evidence):
            raise ValueError("requested_evidence MUST be unique")
        if len(self.requested_evidence) > 4:
            raise ValueError("requested_evidence MUST contain <= 4 tools")


@dataclass(frozen=True, slots=True)
class ReadInvestigationStep:
    tool_id: ReadToolId
    timeout_seconds: float
    max_results: int
    max_output_bytes: int
    fallback_rank: int = 0

    def __post_init__(self) -> None:
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("step timeout_seconds MUST be in [0.1, 120]")
        if not 1 <= self.max_results <= 64:
            raise ValueError("step max_results MUST be in [1, 64]")
        if not 1_024 <= self.max_output_bytes <= 1_000_000:
            raise ValueError("step max_output_bytes MUST be in [1024, 1000000]")
        if self.fallback_rank < 0:
            raise ValueError("fallback_rank MUST be non-negative")


@dataclass(frozen=True, slots=True)
class ReadInvestigationPlan:
    request: ReadInvestigationRequest
    steps: tuple[ReadInvestigationStep, ...]

    def __post_init__(self) -> None:
        if not self.steps or self.steps[0].tool_id is not ReadToolId.RESOLVE_RESOURCE:
            raise ValueError("read investigation plan MUST resolve the resource first")
        tool_ids = tuple(step.tool_id for step in self.steps)
        if len(set(tool_ids)) != len(tool_ids):
            raise ValueError("read investigation plan tools MUST be unique")
        if len(self.steps) > self.request.budget.max_tool_calls:
            raise ValueError("read investigation plan exceeds max_tool_calls")

    @property
    def evidence_steps(self) -> tuple[ReadInvestigationStep, ...]:
        return self.steps[1:]


class ReadInvestigationOutcome(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NONE = "none"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class ReadInvestigationResult:
    request: ReadInvestigationRequest
    outcome: ReadInvestigationOutcome
    resolution: ResourceResolution
    evidence: tuple[ReadEvidenceEnvelope, ...]
    receipts: tuple[ToolCallReceipt, ...]
    progress_kinds: tuple[str, ...]
    started_at: datetime
    finished_at: datetime

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("investigation result timestamps MUST be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("investigation finished_at MUST be >= started_at")
        if len(self.receipts) > self.request.budget.max_tool_calls:
            raise ValueError("investigation receipts exceed max_tool_calls")
        if len(self.evidence) > 4:
            raise ValueError("investigation evidence MUST contain <= 4 envelopes")
        if not self.progress_kinds or self.progress_kinds[-1] != "investigation.completed":
            raise ValueError("investigation progress MUST end with one terminal event")
        if self.progress_kinds.count("investigation.completed") != 1:
            raise ValueError("investigation progress MUST contain one terminal event")

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(ref for envelope in self.evidence for ref in envelope.evidence_refs)


def _identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_ID or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


__all__ = [
    "ReadInvestigationBudget",
    "ReadInvestigationOutcome",
    "ReadInvestigationPlan",
    "ReadInvestigationRequest",
    "ReadInvestigationResult",
    "ReadInvestigationStep",
]
