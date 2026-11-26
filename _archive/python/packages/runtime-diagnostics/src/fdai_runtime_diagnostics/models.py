"""Validated content-free development profile packet contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitRevision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ProfileModel(BaseModel):
    """Forbid undeclared diagnostic fields and mutation after validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StageLatency(ProfileModel):
    name: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9._-]+$")]
    count: Annotated[int, Field(ge=1, le=1000)]
    p50_ms: Annotated[float, Field(ge=0)]
    p95_ms: Annotated[float, Field(ge=0)]
    p99_ms: Annotated[float, Field(ge=0)]
    max_ms: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.p50_ms <= self.p95_ms <= self.p99_ms <= self.max_ms:
            raise ValueError("stage latency percentiles MUST be ordered")
        return self


class ProcessSnapshot(ProfileModel):
    cpu_user_ms: Annotated[float, Field(ge=0)]
    cpu_system_ms: Annotated[float, Field(ge=0)]
    rss_bytes: Annotated[int, Field(ge=0)]
    vms_bytes: Annotated[int, Field(ge=0)]
    peak_rss_bytes: Annotated[int, Field(ge=0)]
    thread_count: Annotated[int, Field(ge=1)]
    open_fd_count: Annotated[int, Field(ge=-1)]
    gc_generation_counts: tuple[int, int, int]
    gc_collections: Annotated[int, Field(ge=0)]


class CpuProfileEntry(ProfileModel):
    path: Annotated[str, Field(min_length=1, max_length=512)]
    line: Annotated[int, Field(ge=0)]
    function: Annotated[str, Field(min_length=1, max_length=256)]
    primitive_calls: Annotated[int, Field(ge=0)]
    total_calls: Annotated[int, Field(ge=0)]
    self_time_ms: Annotated[float, Field(ge=0)]
    cumulative_time_ms: Annotated[float, Field(ge=0)]


class HeapProfileEntry(ProfileModel):
    path: Annotated[str, Field(min_length=1, max_length=512)]
    line: Annotated[int, Field(ge=1)]
    size_diff_bytes: int
    count_diff: int
    current_size_bytes: Annotated[int, Field(ge=0)]


DecisionToken = Annotated[
    str,
    Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9~][A-Za-z0-9_.:@~/-]{0,95}$"),
]
DecisionKey = Annotated[str, Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_]{0,47}$")]
DecisionNumber = Annotated[int, Field(ge=-1, le=10_000_000)]
DecisionValue = (
    bool
    | DecisionNumber
    | DecisionToken
    | Annotated[tuple[DecisionToken | DecisionNumber, ...], Field(max_length=32)]
)


class DecisionStep(ProfileModel):
    """One typed decision point; tokens, numbers, and flags only, never text."""

    stage: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
    attributes: Annotated[dict[DecisionKey, DecisionValue], Field(max_length=32)]


class DecisionCue(ProfileModel):
    """One deterministic review cue that points at the step to inspect."""

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    step: Annotated[int, Field(ge=0, lt=64)]


class DecisionTrace(ProfileModel):
    """Content-free decision chain of one completed semantic turn."""

    sequence: Annotated[int, Field(ge=1)]
    recorded_at: datetime
    session: Annotated[str, Field(pattern=r"^s[0-9]{1,6}$")]
    turn_sequence: Annotated[int, Field(ge=0, le=1_000_000)] | None
    steps: Annotated[tuple[DecisionStep, ...], Field(min_length=1, max_length=64)]
    cues: Annotated[tuple[DecisionCue, ...], Field(max_length=32)]

    @field_validator("recorded_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision trace time MUST be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _cues_point_at_steps(self) -> Self:
        if any(cue.step >= len(self.steps) for cue in self.cues):
            raise ValueError("decision cue MUST point at an existing step")
        return self


class _DevelopmentProfilePacketBody(ProfileModel):
    schema_version: Literal["1.0.0", "1.1.0"]
    profile_id: Annotated[
        str,
        Field(
            min_length=36,
            max_length=36,
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        ),
    ]
    service_id: Annotated[
        str,
        Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9-]{0,79}$"),
    ]
    capture_kind: Literal["snapshot", "profile"]
    source_revision: GitRevision
    service_input_digest: HexDigest
    worktree_digest: HexDigest
    runtime_scope_receipt_digest: Sha256Digest
    started_at: datetime
    completed_at: datetime
    requested_duration_ms: Annotated[int, Field(ge=0, le=30_000)]
    measured_duration_ms: Annotated[int, Field(ge=0, le=60_000)]
    event_loop_lag_ms: Annotated[float, Field(ge=0)]
    before: ProcessSnapshot
    after: ProcessSnapshot
    stages: Annotated[tuple[StageLatency, ...], Field(max_length=128)]
    cpu_top: Annotated[tuple[CpuProfileEntry, ...], Field(max_length=50)]
    heap_top: Annotated[tuple[HeapProfileEntry, ...], Field(max_length=50)]
    python_heap_before_bytes: Annotated[int | None, Field(ge=0)]
    python_heap_after_bytes: Annotated[int | None, Field(ge=0)]
    python_heap_peak_bytes: Annotated[int | None, Field(ge=0)]
    untracked_memory_bytes: int | None
    limitations: Annotated[tuple[str, ...], Field(max_length=16)]
    complete: bool
    external_state_authority: Literal[False]
    execution_authority: Literal[False]
    decisions: Annotated[
        tuple[DecisionTrace, ...],
        Field(max_length=50, exclude_if=lambda value: not value),
    ] = ()
    decisions_evicted: Annotated[int, Field(ge=0, exclude_if=lambda value: not value)] = 0
    decisions_rejected: Annotated[int, Field(ge=0, exclude_if=lambda value: not value)] = 0

    @field_validator("started_at", "completed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("development profile times MUST be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("development profile completion MUST follow start")
        if self.capture_kind == "snapshot" and self.requested_duration_ms != 0:
            raise ValueError("snapshot profile MUST have zero requested duration")
        if self.capture_kind == "profile" and self.requested_duration_ms < 1:
            raise ValueError("profile capture MUST have a positive duration")
        if self.complete is bool(self.limitations):
            raise ValueError("development profile completeness conflicts with limitations")
        if self.schema_version == "1.0.0" and (
            self.decisions or self.decisions_evicted or self.decisions_rejected
        ):
            raise ValueError("development profile schema 1.0.0 cannot carry decision traces")
        return self


class DevelopmentProfilePacket(_DevelopmentProfilePacketBody):
    """One digest-bound local profile packet with no operational authority."""

    packet_digest: Sha256Digest

    @classmethod
    def build(cls, **values: object) -> Self:
        body = _DevelopmentProfilePacketBody.model_validate(values)
        serialized = body.model_dump(mode="json")
        return cls(**serialized, packet_digest=_digest(serialized))

    @model_validator(mode="after")
    def _digest_matches(self) -> Self:
        expected = _digest(self.model_dump(mode="json", exclude={"packet_digest"}))
        if self.packet_digest != expected:
            raise ValueError("development profile packet digest does not match content")
        return self


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CpuProfileEntry",
    "DecisionCue",
    "DecisionStep",
    "DecisionTrace",
    "DevelopmentProfilePacket",
    "HeapProfileEntry",
    "ProcessSnapshot",
    "StageLatency",
]
