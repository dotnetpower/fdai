"""Versioned Core-to-Operator background-task projection transport."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest

BACKGROUND_TASK_PROJECTION_TOPIC = "core.background-task.projections"
BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP = "operator-background-task-projection-v1"

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
BoundedId = Annotated[str, Field(min_length=1, max_length=256)]
CompletionState = Literal["pending", "sending", "failed", "delivered", "abandoned"]
TaskStatus = Literal[
    "queued",
    "claimed",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "unknown",
]
RecordKind = Literal["snapshot", "progress"]
_TASK_ID_PATTERN = r"^background-task-(snapshot|progress)-[a-f0-9]{32}$"
_TERMINAL_TASK_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out", "unknown"})
_MAX_BIGINT = 9_223_372_036_854_775_807
_COMPLETION_STATE_RANK = {
    "pending": 1,
    "sending": 2,
    "failed": 3,
    "delivered": 4,
    "abandoned": 5,
}


class BackgroundTaskProjectionContract(BaseModel):
    """Provide a fail-closed immutable envelope for background-task projections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and any(ord(character) < 32 for character in value):
            raise ValueError("background task projection text MUST NOT contain control characters")
        return value


class BackgroundTaskProjectionBudget(BackgroundTaskProjectionContract):
    """Carry the bounded detached-task budget used for Operator reads."""

    max_wall_seconds: Annotated[int, Field(ge=1, le=3_600)]
    max_tokens: Annotated[int, Field(ge=1, le=32_768)]
    max_cost_microusd: Annotated[int, Field(ge=0, le=10_000_000)]
    max_tool_calls: Annotated[int, Field(ge=0, le=100)]
    max_progress_events: Annotated[int, Field(ge=1, le=256)]


class BackgroundTaskProjectionUsage(BackgroundTaskProjectionContract):
    """Carry bounded usage without provider billing authority."""

    tokens: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    cost_microusd: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    tool_calls: Annotated[int, Field(ge=0, le=100)] = 0


class BackgroundTaskProjectionEnvelope(BackgroundTaskProjectionContract):
    """Transfer one idempotent background-task snapshot or progress record."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    projection_id: Annotated[str, Field(pattern=_TASK_ID_PATTERN)]
    record_kind: RecordKind
    task_id: BoundedId
    owner_principal_id: BoundedId
    attempt_id: BoundedId
    recorded_at: datetime
    retention_until: datetime
    usage: BackgroundTaskProjectionUsage
    projection_digest: Digest
    execution_authority: Literal[False] = False

    task_kind: Literal["read_only_investigation"] | None = None
    status: TaskStatus | None = None
    revision: Annotated[int, Field(ge=1, le=2_147_483_647)] | None = None
    projection_sequence: Annotated[int, Field(ge=1, le=2_147_483_647)] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    lease_expires_at: datetime | None = None
    budget: BackgroundTaskProjectionBudget | None = None
    request_summary: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    request_truncated: bool | None = None
    accountable_agent: Literal["Heimdall"] | None = None
    result_summary: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    result_truncated: bool | None = None
    evidence_refs: Annotated[tuple[BoundedId, ...], Field(max_length=16)] = ()
    evidence_truncated: bool | None = None
    terminal_reason: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    completion_state: CompletionState | None = None
    completion_attempt_count: Annotated[int, Field(ge=0, le=8)] | None = None
    progress_watermark: Annotated[int, Field(ge=0, le=_MAX_BIGINT)] | None = None

    progress_sequence: Annotated[int, Field(ge=0, le=255)] | None = None
    progress_order: Annotated[int, Field(ge=1, le=_MAX_BIGINT)] | None = None
    progress_kind: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    progress_message: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    progress_at: datetime | None = None

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("background task evidence_refs MUST be unique")
        return value

    @model_validator(mode="after")
    def _validate_record(self) -> BackgroundTaskProjectionEnvelope:
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.retention_until, "retention_until")
        if self.record_kind == "snapshot":
            self._validate_snapshot()
        else:
            self._validate_progress()
        if self.projection_digest != background_task_projection_digest(self):
            raise ValueError("background task projection digest does not match its content")
        expected_id = background_task_projection_id(
            record_kind=self.record_kind,
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            sequence=(
                self.projection_sequence
                if self.record_kind == "snapshot"
                else self.progress_sequence
            ),
        )
        if self.projection_id != expected_id:
            raise ValueError("background task projection id does not match its content")
        return self

    def _validate_snapshot(self) -> None:
        required = (
            self.task_kind,
            self.status,
            self.revision,
            self.projection_sequence,
            self.created_at,
            self.updated_at,
            self.budget,
            self.request_truncated,
            self.result_truncated,
            self.evidence_truncated,
        )
        if any(item is None for item in required):
            raise ValueError("background task snapshot record is incomplete")
        created_at = self.created_at
        updated_at = self.updated_at
        if created_at is None or updated_at is None:  # pragma: no cover - guarded above
            raise ValueError("background task snapshot record is incomplete")
        _require_aware(created_at, "created_at")
        _require_aware(updated_at, "updated_at")
        if not created_at <= updated_at <= self.recorded_at <= self.retention_until:
            raise ValueError("background task snapshot timestamps MUST be ordered")
        if self.completion_state is None:
            if self.completion_attempt_count is not None:
                raise ValueError("snapshot completion_attempt_count requires completion_state")
        else:
            if self.status not in _TERMINAL_TASK_STATUSES:
                raise ValueError("background task completion_state requires terminal status")
            if self.completion_attempt_count is None:
                raise ValueError("snapshot completion_state requires completion_attempt_count")
        if self.status in _TERMINAL_TASK_STATUSES:
            started_at = self.started_at
            finished_at = self.finished_at
            if (
                self.terminal_reason is None
                or started_at is None
                or finished_at is None
                or self.progress_watermark is None
            ):
                raise ValueError("terminal background task snapshot is incomplete")
            _require_aware(started_at, "started_at")
            _require_aware(finished_at, "finished_at")
            if not started_at <= finished_at <= self.recorded_at:
                raise ValueError("terminal background task times MUST be ordered")
        else:
            if (
                any(
                    value is not None
                    for value in (
                        self.terminal_reason,
                        self.started_at,
                        self.finished_at,
                        self.result_summary,
                        self.completion_state,
                        self.completion_attempt_count,
                        self.progress_watermark,
                    )
                )
                or self.evidence_refs
            ):
                raise ValueError(
                    "non-terminal background task snapshot carries terminal-only fields"
                )
        if any(
            value is not None
            for value in (
                self.progress_order,
                self.progress_sequence,
                self.progress_kind,
                self.progress_message,
                self.progress_at,
            )
        ):
            raise ValueError("background task snapshot cannot carry progress fields")

    def _validate_progress(self) -> None:
        required = (
            self.progress_sequence,
            self.progress_order,
            self.progress_kind,
            self.progress_message,
            self.progress_at,
        )
        if any(item is None for item in required):
            raise ValueError("background task progress record is incomplete")
        progress_at = self.progress_at
        if progress_at is None:  # pragma: no cover - guarded above
            raise ValueError("background task progress record is incomplete")
        _require_aware(progress_at, "progress_at")
        if not progress_at <= self.recorded_at <= self.retention_until:
            raise ValueError("background task progress timestamps MUST be ordered")
        if self.budget is not None:
            raise ValueError("background task progress cannot carry a budget")
        if (
            any(
                value is not None
                for value in (
                    self.task_kind,
                    self.status,
                    self.revision,
                    self.projection_sequence,
                    self.created_at,
                    self.updated_at,
                    self.lease_expires_at,
                    self.request_summary,
                    self.request_truncated,
                    self.accountable_agent,
                    self.result_summary,
                    self.result_truncated,
                    self.evidence_truncated,
                    self.terminal_reason,
                    self.started_at,
                    self.finished_at,
                    self.completion_state,
                    self.completion_attempt_count,
                    self.progress_watermark,
                )
            )
            or self.evidence_refs
        ):
            raise ValueError("background task progress cannot carry snapshot-only fields")


def background_task_completion_subsequence(
    completion_state: CompletionState | None,
    completion_attempt_count: int | None,
) -> int:
    """Return the snapshot tie-breaker for completion-state transitions."""

    if completion_state is None:
        if completion_attempt_count is not None:
            raise ValueError("completion_attempt_count requires completion_state")
        return 0
    if completion_attempt_count is None:
        raise ValueError("completion_state requires completion_attempt_count")
    return (completion_attempt_count * 10) + _COMPLETION_STATE_RANK[completion_state]


def background_task_snapshot_sequence(
    revision: int,
    completion_state: CompletionState | None,
    completion_attempt_count: int | None,
) -> int:
    """Return the monotonic per-task snapshot sequence for duplicates and reorders."""

    if revision < 1:
        raise ValueError("background task revision MUST be positive")
    return revision * 100 + background_task_completion_subsequence(
        completion_state,
        completion_attempt_count,
    )


def background_task_projection_id(
    *,
    record_kind: RecordKind,
    task_id: str,
    attempt_id: str,
    sequence: int | None,
) -> str:
    """Return the replay-stable identity for one task snapshot or progress record."""

    if sequence is None:
        raise ValueError("background task projection sequence is required")
    digest = hashlib.sha256(
        f"{record_kind}\x00{task_id}\x00{attempt_id}\x00{sequence}".encode("utf-8")
    ).hexdigest()
    return f"background-task-{record_kind}-{digest[:32]}"


def background_task_projection_digest(record: BackgroundTaskProjectionEnvelope) -> str:
    """Return the replay-stable content digest for one projection record."""

    return canonical_digest(
        record.model_dump(
            mode="json",
            exclude={"projection_digest"},
            exclude_none=True,
        )
    )


def build_background_task_snapshot(
    *,
    task_id: str,
    owner_principal_id: str,
    attempt_id: str,
    task_kind: Literal["read_only_investigation"],
    status: TaskStatus,
    revision: int,
    created_at: datetime,
    updated_at: datetime,
    retention_until: datetime,
    usage: BackgroundTaskProjectionUsage,
    budget: BackgroundTaskProjectionBudget,
    recorded_at: datetime,
    lease_expires_at: datetime | None = None,
    request_summary: str | None = None,
    request_truncated: bool = False,
    accountable_agent: Literal["Heimdall"] | None = None,
    result_summary: str | None = None,
    result_truncated: bool = False,
    evidence_refs: tuple[str, ...] = (),
    evidence_truncated: bool = False,
    terminal_reason: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    completion_state: CompletionState | None = None,
    completion_attempt_count: int | None = None,
    progress_watermark: int | None = None,
) -> BackgroundTaskProjectionEnvelope:
    """Build one validated task snapshot with deterministic identity and digest."""

    projection_sequence = background_task_snapshot_sequence(
        revision,
        completion_state,
        completion_attempt_count,
    )
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "record_kind": "snapshot",
        "projection_id": background_task_projection_id(
            record_kind="snapshot",
            task_id=task_id,
            attempt_id=attempt_id,
            sequence=projection_sequence,
        ),
        "task_id": task_id,
        "owner_principal_id": owner_principal_id,
        "attempt_id": attempt_id,
        "recorded_at": _json_datetime(recorded_at),
        "retention_until": _json_datetime(retention_until),
        "usage": usage.model_dump(mode="json"),
        "task_kind": task_kind,
        "status": status,
        "revision": revision,
        "projection_sequence": projection_sequence,
        "created_at": _json_datetime(created_at),
        "updated_at": _json_datetime(updated_at),
        "lease_expires_at": _json_datetime(lease_expires_at),
        "budget": budget.model_dump(mode="json"),
        "request_summary": request_summary,
        "request_truncated": request_truncated,
        "accountable_agent": accountable_agent,
        "result_summary": result_summary,
        "result_truncated": result_truncated,
        "evidence_refs": list(evidence_refs),
        "evidence_truncated": evidence_truncated,
        "terminal_reason": terminal_reason,
        "started_at": _json_datetime(started_at),
        "finished_at": _json_datetime(finished_at),
        "completion_state": completion_state,
        "completion_attempt_count": completion_attempt_count,
        "progress_watermark": progress_watermark,
        "execution_authority": False,
    }
    return BackgroundTaskProjectionEnvelope.model_validate(
        {**material, "projection_digest": _digest_material(material)}
    )


def build_background_task_progress(
    *,
    task_id: str,
    owner_principal_id: str,
    attempt_id: str,
    progress_sequence: int,
    progress_order: int,
    progress_kind: str,
    progress_message: str,
    progress_at: datetime,
    retention_until: datetime,
    usage: BackgroundTaskProjectionUsage,
    recorded_at: datetime | None = None,
) -> BackgroundTaskProjectionEnvelope:
    """Build one validated task progress record with deterministic identity and digest."""

    effective_recorded_at = progress_at if recorded_at is None else recorded_at
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "record_kind": "progress",
        "projection_id": background_task_projection_id(
            record_kind="progress",
            task_id=task_id,
            attempt_id=attempt_id,
            sequence=progress_sequence,
        ),
        "task_id": task_id,
        "owner_principal_id": owner_principal_id,
        "attempt_id": attempt_id,
        "recorded_at": _json_datetime(effective_recorded_at),
        "retention_until": _json_datetime(retention_until),
        "usage": usage.model_dump(mode="json"),
        "progress_sequence": progress_sequence,
        "progress_order": progress_order,
        "progress_kind": progress_kind,
        "progress_message": progress_message,
        "progress_at": _json_datetime(progress_at),
        "evidence_refs": [],
        "execution_authority": False,
    }
    return BackgroundTaskProjectionEnvelope.model_validate(
        {**material, "projection_digest": _digest_material(material)}
    )


def _json_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _digest_material(material: Mapping[str, object]) -> str:
    return canonical_digest({key: value for key, value in material.items() if value is not None})


def _require_aware(value: datetime | None, field: str) -> None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"background task {field} MUST be timezone-aware")


__all__ = [
    "BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP",
    "BACKGROUND_TASK_PROJECTION_TOPIC",
    "BackgroundTaskProjectionBudget",
    "BackgroundTaskProjectionContract",
    "BackgroundTaskProjectionEnvelope",
    "BackgroundTaskProjectionUsage",
    "background_task_completion_subsequence",
    "background_task_projection_digest",
    "background_task_projection_id",
    "background_task_snapshot_sequence",
    "build_background_task_progress",
    "build_background_task_snapshot",
]
