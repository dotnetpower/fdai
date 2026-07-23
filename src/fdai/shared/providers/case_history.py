"""Provider contracts for revisioned case-history metadata and artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.shared.contracts.models import ForecastOutcomeLabel


@dataclass(frozen=True, slots=True)
class CaseHistoryRevisionRecord:
    case_id: str
    revision: int
    kind: str
    correlation_id: str
    purpose: str
    access_scope_digest: str
    manifest_digest: str
    parent_manifest_digest: str | None
    source_set_digest: str
    storage_ref: str | None
    artifact_size: int
    outcome_label: str
    detector_id: str
    detector_version: str
    metric: str
    event_time_cutoff: datetime
    created_by_agent: str
    sealed_at: datetime
    retention_until: datetime
    deletion_due_at: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None
    deleted_at: datetime | None = None
    state_revision: int = 0
    deletion_started_at: datetime | None = None
    deletion_storage_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.case_id,
                self.kind,
                self.correlation_id,
                self.purpose,
                self.outcome_label,
                self.detector_id,
                self.detector_version,
                self.metric,
                self.created_by_agent,
            )
        ):
            raise ValueError("case history record identity MUST be non-empty")
        if self.revision < 1 or self.artifact_size < 0:
            raise ValueError("case history revision MUST be positive and size non-negative")
        if self.state_revision == 0:
            object.__setattr__(self, "state_revision", self.revision)
        if self.state_revision < self.revision:
            raise ValueError("case history state revision MUST cover the case revision")
        try:
            ForecastOutcomeLabel(self.outcome_label)
        except ValueError as exc:
            raise ValueError("case history outcome_label is unsupported") from exc
        for name, value in (
            ("access_scope_digest", self.access_scope_digest),
            ("manifest_digest", self.manifest_digest),
            ("source_set_digest", self.source_set_digest),
        ):
            _digest(name, value)
        if self.parent_manifest_digest is not None:
            _digest("parent_manifest_digest", self.parent_manifest_digest)
        timestamps = (
            self.event_time_cutoff,
            self.sealed_at,
            self.retention_until,
            self.deletion_due_at,
        )
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("case history timestamps MUST be timezone-aware")
        if not self.event_time_cutoff <= self.sealed_at <= self.retention_until:
            raise ValueError("case history cutoff, seal, and retention MUST be ordered")
        if self.retention_until > self.deletion_due_at:
            raise ValueError("case history deletion MUST NOT precede retention")
        if self.legal_hold and (self.legal_hold_ref is None or not self.legal_hold_ref.strip()):
            raise ValueError("case history legal hold MUST reference its authority")
        if not self.legal_hold and self.legal_hold_ref is not None:
            raise ValueError("case history legal hold metadata is inconsistent")
        if self.deletion_started_at is not None:
            if self.deletion_started_at.tzinfo is None:
                raise ValueError("case history deletion_started_at MUST be timezone-aware")
            if self.deletion_started_at < self.deletion_due_at:
                raise ValueError("case history deletion MUST NOT start before it is due")
        if self.deletion_storage_refs and self.deletion_started_at is None:
            raise ValueError("case history deletion refs require a deletion intent")
        if self.deleted_at is None:
            if not self.storage_ref or self.artifact_size < 1:
                raise ValueError("active case history MUST carry artifact storage and size")
            if self.deletion_started_at is not None and not self.deletion_storage_refs:
                raise ValueError("pending case history deletion MUST retain artifact refs")
        elif self.storage_ref is not None or self.artifact_size != 0:
            raise ValueError("deleted case history MUST clear artifact storage and size")
        elif self.deleted_at.tzinfo is None:
            raise ValueError("case history deleted_at MUST be timezone-aware")
        elif self.deleted_at < self.deletion_due_at:
            raise ValueError("case history MUST NOT be deleted before it is due")
        elif self.deletion_started_at is not None and self.deleted_at < self.deletion_started_at:
            raise ValueError("case history deletion timestamps MUST be ordered")
        elif self.deletion_storage_refs:
            raise ValueError("deleted case history MUST clear deletion artifact refs")


@runtime_checkable
class CaseHistoryMetadataStore(Protocol):
    async def append_revision(self, record: CaseHistoryRevisionRecord) -> bool: ...

    async def latest(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
    ) -> CaseHistoryRevisionRecord | None: ...

    async def list_closed(
        self,
        *,
        access_scope_digest: str,
        purpose: str,
        outcome_labels: tuple[str, ...],
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]: ...

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]: ...

    async def mark_deletion_started(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        storage_refs: tuple[str, ...],
        started_at: datetime,
    ) -> CaseHistoryRevisionRecord: ...

    async def mark_deleted(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        deleted_at: datetime,
    ) -> CaseHistoryRevisionRecord: ...


@runtime_checkable
class CaseHistoryArtifactStore(Protocol):
    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool: ...

    async def get(self, storage_ref: str) -> bytes | None: ...

    async def delete(self, storage_ref: str) -> None: ...


def _digest(name: str, value: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"case history {name} MUST be lowercase SHA-256")


__all__ = [
    "CaseHistoryArtifactStore",
    "CaseHistoryMetadataStore",
    "CaseHistoryRevisionRecord",
]
