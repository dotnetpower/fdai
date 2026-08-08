"""Immutable source snapshots and access contracts for trajectory projection."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TrajectorySourceKind(StrEnum):
    AUDIT = "audit"
    CONVERSATION = "conversation"
    TOOL = "tool"
    APPROVAL = "approval"
    OUTCOME = "outcome"


@dataclass(frozen=True, slots=True)
class TrajectoryBatchFilters:
    """Server-side batch filters; empty fields mean no restriction."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    verticals: tuple[str, ...] = ()
    action_types: tuple[str, ...] = ()
    tiers: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    evidence_profiles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.started_at is not None and self.started_at.tzinfo is None:
            raise ValueError("started_at MUST be timezone-aware")
        if self.ended_at is not None and self.ended_at.tzinfo is None:
            raise ValueError("ended_at MUST be timezone-aware")
        if (
            self.started_at is not None
            and self.ended_at is not None
            and self.ended_at < self.started_at
        ):
            raise ValueError("ended_at MUST be on or after started_at")
        for name, values in (
            ("verticals", self.verticals),
            ("action_types", self.action_types),
            ("tiers", self.tiers),
            ("outcomes", self.outcomes),
            ("evidence_profiles", self.evidence_profiles),
        ):
            if values != tuple(sorted(set(values))) or any(not value for value in values):
                raise ValueError(f"{name} MUST contain unique non-empty values in sorted order")


@dataclass(frozen=True, slots=True)
class AuthorizedTrajectoryScope:
    principal_id: str
    access_scope: str
    principal_scope_digest: str

    def __post_init__(self) -> None:
        if not self.principal_id or not self.access_scope:
            raise ValueError("authorized trajectory principal and scope MUST be non-empty")
        _digest("principal_scope_digest", self.principal_scope_digest)


@dataclass(frozen=True, slots=True)
class ImmutableTrajectorySnapshot:
    """Bounded record projection with source digest and no unrestricted body."""

    source_kind: TrajectorySourceKind
    record_id: str
    record_digest: str
    trace_id: str
    correlation_id: str
    occurred_at: datetime
    step_kind: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not all((self.record_id, self.trace_id, self.correlation_id, self.step_kind)):
            raise ValueError("trajectory snapshot identity fields MUST be non-empty")
        _digest("record_digest", self.record_digest)
        if self.occurred_at.tzinfo is None:
            raise ValueError("trajectory snapshot occurred_at MUST be timezone-aware")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))


class TrajectoryDatasetState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    QUARANTINED = "quarantined"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class TrajectoryDatasetRecord:
    """Durable metadata only; exported customer records stay outside the store."""

    dataset_id: str
    purpose: str
    access_scope: str
    principal_scope_digest: str
    state: TrajectoryDatasetState
    schema_version: str
    storage_ref: str | None
    record_count: int
    dataset_checksum: str | None
    manifest_checksum: str | None
    created_at: datetime
    retention_until: datetime
    deletion_due_at: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.record_count < 0:
            raise ValueError("trajectory dataset record_count MUST be non-negative")
        _digest("principal_scope_digest", self.principal_scope_digest)
        for checksum_name, checksum_value in (
            ("dataset_checksum", self.dataset_checksum),
            ("manifest_checksum", self.manifest_checksum),
        ):
            if checksum_value is not None:
                _digest(checksum_name, checksum_value)
        for timestamp_name, timestamp_value in (
            ("created_at", self.created_at),
            ("retention_until", self.retention_until),
            ("deletion_due_at", self.deletion_due_at),
        ):
            if timestamp_value.tzinfo is None:
                raise ValueError(f"trajectory dataset {timestamp_name} MUST be timezone-aware")
        if not self.created_at <= self.retention_until <= self.deletion_due_at:
            raise ValueError("trajectory dataset retention timestamps are not ordered")
        if self.legal_hold != (self.legal_hold_ref is not None):
            raise ValueError("trajectory dataset legal hold metadata is inconsistent")
        if self.state is TrajectoryDatasetState.COMPLETED:
            if not all((self.storage_ref, self.dataset_checksum, self.manifest_checksum)):
                raise ValueError("completed trajectory dataset MUST carry storage and checksums")
        if self.state is TrajectoryDatasetState.DELETED:
            if self.storage_ref is not None or self.deleted_at is None:
                raise ValueError(
                    "deleted trajectory dataset MUST clear storage and carry deleted_at"
                )
        elif self.deleted_at is not None:
            raise ValueError("only deleted trajectory dataset can carry deleted_at")


def _digest(name: str, value: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"trajectory {name} MUST be a lowercase SHA-256 digest")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): _freeze_value(child) for key, child in value.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(child) for child in value)
    return value


class TrajectoryDatasetStore(Protocol):
    async def put(self, record: TrajectoryDatasetRecord) -> TrajectoryDatasetRecord: ...

    async def get(
        self,
        dataset_id: str,
        *,
        access_scope: str,
    ) -> TrajectoryDatasetRecord | None: ...

    async def list(
        self,
        *,
        access_scope: str,
        purpose: str,
        limit: int,
    ) -> tuple[TrajectoryDatasetRecord, ...]: ...

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[TrajectoryDatasetRecord, ...]: ...

    async def mark_deleted(
        self,
        dataset_id: str,
        *,
        deleted_at: datetime,
    ) -> TrajectoryDatasetRecord: ...


class TrajectoryArtifactDeleter(Protocol):
    async def delete(self, storage_ref: str) -> None: ...


class TrajectoryAccessAuthorizer(Protocol):
    async def authorize(
        self,
        *,
        principal_id: str,
        access_scope: str,
        purpose: str,
    ) -> AuthorizedTrajectoryScope: ...


class AuditSnapshotProvider(Protocol):
    async def snapshot(
        self,
        *,
        scope: AuthorizedTrajectoryScope,
        filters: TrajectoryBatchFilters,
    ) -> tuple[ImmutableTrajectorySnapshot, ...]: ...


class ConversationSnapshotProvider(Protocol):
    async def snapshot(
        self,
        *,
        scope: AuthorizedTrajectoryScope,
        filters: TrajectoryBatchFilters,
    ) -> tuple[ImmutableTrajectorySnapshot, ...]: ...


class ToolSnapshotProvider(Protocol):
    async def snapshot(
        self,
        *,
        scope: AuthorizedTrajectoryScope,
        filters: TrajectoryBatchFilters,
    ) -> tuple[ImmutableTrajectorySnapshot, ...]: ...


class ApprovalSnapshotProvider(Protocol):
    async def snapshot(
        self,
        *,
        scope: AuthorizedTrajectoryScope,
        filters: TrajectoryBatchFilters,
    ) -> tuple[ImmutableTrajectorySnapshot, ...]: ...


class OutcomeSnapshotProvider(Protocol):
    async def snapshot(
        self,
        *,
        scope: AuthorizedTrajectoryScope,
        filters: TrajectoryBatchFilters,
    ) -> tuple[ImmutableTrajectorySnapshot, ...]: ...


__all__ = [
    "ApprovalSnapshotProvider",
    "AuditSnapshotProvider",
    "AuthorizedTrajectoryScope",
    "ConversationSnapshotProvider",
    "ImmutableTrajectorySnapshot",
    "OutcomeSnapshotProvider",
    "ToolSnapshotProvider",
    "TrajectoryAccessAuthorizer",
    "TrajectoryArtifactDeleter",
    "TrajectoryBatchFilters",
    "TrajectoryDatasetRecord",
    "TrajectoryDatasetState",
    "TrajectoryDatasetStore",
    "TrajectorySourceKind",
]
