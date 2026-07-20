"""Versioned, access-scoped trajectory export contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

TRAJECTORY_SCHEMA_VERSION: Final = "1.0"

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:/-]+$")
_MAX_IDENTIFIER_CHARS = 512
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "auth_header",
        "authorization",
        "chain_of_thought",
        "credential",
        "credentials",
        "hidden_reasoning",
        "prompt",
        "raw_attachment",
        "raw_cloud_payload",
        "raw_output",
        "raw_prompt",
        "token",
        "tokens",
    }
)


class TrajectoryTerminalOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ABSTAINED = "abstained"
    AMBIGUOUS = "ambiguous"


class TrajectoryStepKind(StrEnum):
    NORMALIZED_INPUT_REFERENCE = "normalized_input_reference"
    ROUTING_DECISION = "routing_decision"
    ASSISTANT_OUTPUT = "assistant_output"
    TOOL_REQUEST = "tool_request"
    TOOL_RECEIPT = "tool_receipt"
    ACTION_REQUEST = "action_request"
    ACTION_RECEIPT = "action_receipt"
    VERIFIER_RESULT = "verifier_result"
    RISK_RESULT = "risk_result"
    APPROVAL = "approval"
    TERMINAL_OUTCOME = "terminal_outcome"
    ROLLBACK_STATE = "rollback_state"


_EXCERPT_LIMITS = {
    TrajectoryStepKind.NORMALIZED_INPUT_REFERENCE: 4 * 1024,
    TrajectoryStepKind.ROUTING_DECISION: 8 * 1024,
    TrajectoryStepKind.ASSISTANT_OUTPUT: 16 * 1024,
    TrajectoryStepKind.TOOL_REQUEST: 8 * 1024,
    TrajectoryStepKind.TOOL_RECEIPT: 16 * 1024,
    TrajectoryStepKind.ACTION_REQUEST: 8 * 1024,
    TrajectoryStepKind.ACTION_RECEIPT: 16 * 1024,
    TrajectoryStepKind.VERIFIER_RESULT: 8 * 1024,
    TrajectoryStepKind.RISK_RESULT: 8 * 1024,
    TrajectoryStepKind.APPROVAL: 8 * 1024,
    TrajectoryStepKind.TERMINAL_OUTCOME: 4 * 1024,
    TrajectoryStepKind.ROLLBACK_STATE: 8 * 1024,
}


@dataclass(frozen=True, slots=True)
class SourceRecordDigest:
    """Immutable source identity without copying the source record."""

    record_type: str
    record_id: str
    sha256: str

    def __post_init__(self) -> None:
        _identifier("record_type", self.record_type)
        _identifier("record_id", self.record_id)
        _digest("sha256", self.sha256)


@dataclass(frozen=True, slots=True)
class DatasetGovernance:
    """Purpose limitation, retention, deletion, and legal-hold metadata."""

    purpose: str
    retention_until: datetime
    deletion_due_at: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None

    def __post_init__(self) -> None:
        _identifier("purpose", self.purpose)
        _aware("retention_until", self.retention_until)
        _aware("deletion_due_at", self.deletion_due_at)
        if self.deletion_due_at < self.retention_until:
            raise ValueError("deletion_due_at MUST be on or after retention_until")
        if self.legal_hold != (self.legal_hold_ref is not None):
            raise ValueError("legal_hold and legal_hold_ref MUST be supplied together")
        if self.legal_hold_ref is not None:
            _identifier("legal_hold_ref", self.legal_hold_ref)


@dataclass(frozen=True, slots=True)
class ToolStatistic:
    """One catalog-shaped tool column, including unused tools."""

    tool_id: str
    request_count: int
    success_count: int
    failure_count: int

    def __post_init__(self) -> None:
        _identifier("tool_id", self.tool_id)
        if min(self.request_count, self.success_count, self.failure_count) < 0:
            raise ValueError("tool statistic counts MUST be non-negative")
        if self.success_count + self.failure_count > self.request_count:
            raise ValueError("tool result counts cannot exceed request_count")


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    """One observable step; hidden reasoning and unrestricted payloads are invalid."""

    sequence: int
    occurred_at: datetime
    kind: TrajectoryStepKind
    source: SourceRecordDigest
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("trajectory step sequence MUST be non-negative")
        _aware("occurred_at", self.occurred_at)
        normalized = dict(self.payload)
        _validate_payload(self.kind, normalized)
        object.__setattr__(
            self,
            "payload",
            MappingProxyType({key: _freeze_json(value) for key, value in normalized.items()}),
        )


@dataclass(frozen=True, slots=True)
class TrajectoryEnvelope:
    """Stable trajectory envelope projected only after access authorization."""

    trajectory_id: str
    trace_id: str
    correlation_id: str
    started_at: datetime
    completed_at: datetime
    environment: str
    evidence_profile: str
    principal_scope_digest: str
    model_capability_id: str
    completion_status: TrajectoryTerminalOutcome
    redaction_policy_version: str
    governance: DatasetGovernance
    source_records: tuple[SourceRecordDigest, ...]
    steps: tuple[TrajectoryStep, ...]
    tool_statistics: tuple[ToolStatistic, ...]
    schema_version: str = TRAJECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("trajectory_id", self.trajectory_id),
            ("trace_id", self.trace_id),
            ("correlation_id", self.correlation_id),
            ("environment", self.environment),
            ("evidence_profile", self.evidence_profile),
            ("model_capability_id", self.model_capability_id),
            ("redaction_policy_version", self.redaction_policy_version),
        ):
            _identifier(name, value)
        _aware("started_at", self.started_at)
        _aware("completed_at", self.completed_at)
        if self.completed_at < self.started_at:
            raise ValueError("completed_at MUST be on or after started_at")
        _digest("principal_scope_digest", self.principal_scope_digest)
        if not self.source_records:
            raise ValueError("source_records MUST be non-empty")
        if tuple(sorted(self.source_records, key=_source_key)) != self.source_records:
            raise ValueError("source_records MUST use deterministic record_type/record_id order")
        expected_sequences = tuple(range(len(self.steps)))
        if tuple(step.sequence for step in self.steps) != expected_sequences:
            raise ValueError("steps MUST use contiguous zero-based sequence order")
        if not self.steps or self.steps[-1].kind is not TrajectoryStepKind.TERMINAL_OUTCOME:
            raise ValueError("steps MUST end with an explicit terminal_outcome")
        terminal_value = self.steps[-1].payload.get("outcome")
        if terminal_value != self.completion_status.value:
            raise ValueError("terminal_outcome step MUST match completion_status")
        tool_ids = tuple(item.tool_id for item in self.tool_statistics)
        if tool_ids != tuple(sorted(tool_ids)) or len(tool_ids) != len(set(tool_ids)):
            raise ValueError("tool_statistics MUST contain unique tool ids in catalog order")


def catalog_tool_statistics(
    catalog_tool_ids: tuple[str, ...],
    observed: Mapping[str, tuple[int, int, int]],
) -> tuple[ToolStatistic, ...]:
    """Return stable statistics for every catalog tool, including zero-use tools."""

    catalog = tuple(sorted(set(catalog_tool_ids)))
    unknown = set(observed).difference(catalog)
    if unknown:
        raise ValueError("observed tool ids MUST exist in the catalog")
    return tuple(
        ToolStatistic(
            tool_id=tool_id,
            request_count=observed.get(tool_id, (0, 0, 0))[0],
            success_count=observed.get(tool_id, (0, 0, 0))[1],
            failure_count=observed.get(tool_id, (0, 0, 0))[2],
        )
        for tool_id in catalog
    )


def _validate_payload(kind: TrajectoryStepKind, payload: Mapping[str, object]) -> None:
    forbidden = _payload_keys(payload).intersection(_FORBIDDEN_PAYLOAD_KEYS)
    if forbidden:
        raise ValueError(f"trajectory payload contains forbidden fields: {sorted(forbidden)}")
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("trajectory step payload MUST be canonical JSON data") from exc
    if len(encoded) > _EXCERPT_LIMITS[kind]:
        raise ValueError(f"trajectory {kind.value} payload exceeds its excerpt limit")


def _payload_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key).lower() for key in value} | {
            nested for child in value.values() for nested in _payload_keys(child)
        }
    if isinstance(value, (list, tuple)):
        return {nested for child in value for nested in _payload_keys(child)}
    return set()


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(child) for child in value)
    return value


def _identifier(name: str, value: str) -> None:
    if not value or len(value) > _MAX_IDENTIFIER_CHARS or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a bounded ASCII identifier")


def _digest(name: str, value: str) -> None:
    if _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a lowercase SHA-256 digest")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _source_key(source: SourceRecordDigest) -> tuple[str, str]:
    return source.record_type, source.record_id


__all__ = [
    "TRAJECTORY_SCHEMA_VERSION",
    "DatasetGovernance",
    "SourceRecordDigest",
    "ToolStatistic",
    "TrajectoryEnvelope",
    "TrajectoryStep",
    "TrajectoryStepKind",
    "TrajectoryTerminalOutcome",
    "catalog_tool_statistics",
]
