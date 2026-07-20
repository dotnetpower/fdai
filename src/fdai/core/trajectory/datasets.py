"""Access-scoped dataset metadata reads and retention policy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime

from fdai.shared.providers.trajectory import (
    AuthorizedTrajectoryScope,
    TrajectoryAccessAuthorizer,
    TrajectoryArtifactDeleter,
    TrajectoryDatasetRecord,
    TrajectoryDatasetState,
    TrajectoryDatasetStore,
)


@dataclass(frozen=True, slots=True)
class TrajectoryDatasetQuery:
    principal_id: str
    access_scope: str
    purpose: str
    limit: int = 100

    def __post_init__(self) -> None:
        if not self.purpose or not self.access_scope:
            raise ValueError("trajectory dataset purpose and access_scope are required")
        if not 1 <= self.limit <= 500:
            raise ValueError("trajectory dataset query limit MUST be in [1, 500]")


class TrajectoryDatasetAdminService:
    """Read metadata only after server-side purpose/scope authorization."""

    def __init__(
        self,
        *,
        authorizer: TrajectoryAccessAuthorizer,
        store: TrajectoryDatasetStore,
    ) -> None:
        self._authorizer = authorizer
        self._store = store

    async def list(self, query: TrajectoryDatasetQuery) -> tuple[TrajectoryDatasetRecord, ...]:
        authorized = await self._authorizer.authorize(
            principal_id=query.principal_id,
            access_scope=query.access_scope,
            purpose=query.purpose,
        )
        return await self._store.list(
            access_scope=authorized.access_scope,
            purpose=query.purpose,
            limit=query.limit,
        )

    async def get(
        self,
        *,
        dataset_id: str,
        principal_id: str,
        access_scope: str,
        purpose: str,
    ) -> TrajectoryDatasetRecord | None:
        authorized = await self._authorizer.authorize(
            principal_id=principal_id,
            access_scope=access_scope,
            purpose=purpose,
        )
        record = await self._store.get(dataset_id, access_scope=authorized.access_scope)
        if record is None or record.purpose != purpose:
            return None
        return record


class AllowlistTrajectoryAccessAuthorizer:
    """Deny by default unless principal, scope, and purpose are granted together."""

    def __init__(self, grants: dict[str, frozenset[tuple[str, str]]]) -> None:
        self._grants = {principal: frozenset(items) for principal, items in grants.items()}

    async def authorize(
        self,
        *,
        principal_id: str,
        access_scope: str,
        purpose: str,
    ) -> AuthorizedTrajectoryScope:
        if (access_scope, purpose) not in self._grants.get(principal_id, frozenset()):
            raise PermissionError("trajectory dataset scope is not authorized")
        return AuthorizedTrajectoryScope(
            principal_id=principal_id,
            access_scope=access_scope,
            principal_scope_digest=trajectory_scope_digest(access_scope),
        )


class InMemoryTrajectoryDatasetStore:
    """Deterministic local/test store with legal-hold-aware deletion."""

    def __init__(self) -> None:
        self._records: dict[str, TrajectoryDatasetRecord] = {}

    async def put(self, record: TrajectoryDatasetRecord) -> TrajectoryDatasetRecord:
        existing = self._records.get(record.dataset_id)
        if existing is not None and existing != record:
            raise ValueError("trajectory dataset id was reused with different metadata")
        self._records[record.dataset_id] = record
        return record

    async def get(
        self,
        dataset_id: str,
        *,
        access_scope: str,
    ) -> TrajectoryDatasetRecord | None:
        record = self._records.get(dataset_id)
        if record is None or record.access_scope != access_scope:
            return None
        return record

    async def list(
        self,
        *,
        access_scope: str,
        purpose: str,
        limit: int,
    ) -> tuple[TrajectoryDatasetRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self._records.values()
                    if record.access_scope == access_scope and record.purpose == purpose
                ),
                key=lambda record: (record.created_at, record.dataset_id),
                reverse=True,
            )[:limit]
        )

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[TrajectoryDatasetRecord, ...]:
        if not 1 <= limit <= 5_000:
            raise ValueError("trajectory retention deletion limit MUST be in [1, 5000]")
        return tuple(
            sorted(
                (
                    record
                    for record in self._records.values()
                    if record.state is not TrajectoryDatasetState.DELETED
                    and not record.legal_hold
                    and record.deletion_due_at <= now
                ),
                key=lambda record: (record.deletion_due_at, record.dataset_id),
            )[:limit]
        )

    async def mark_deleted(
        self,
        dataset_id: str,
        *,
        deleted_at: datetime,
    ) -> TrajectoryDatasetRecord:
        record = self._records.get(dataset_id)
        if record is None:
            raise LookupError(f"trajectory dataset was not found: {dataset_id}")
        if record.legal_hold:
            raise PermissionError("trajectory dataset is under legal hold")
        if record.state is TrajectoryDatasetState.DELETED:
            return record
        deleted = replace(
            record,
            state=TrajectoryDatasetState.DELETED,
            storage_ref=None,
            deleted_at=deleted_at,
        )
        self._records[dataset_id] = deleted
        return deleted


class TrajectoryRetentionService:
    """Delete due artifacts before committing their metadata tombstone."""

    def __init__(
        self,
        *,
        store: TrajectoryDatasetStore,
        artifacts: TrajectoryArtifactDeleter,
    ) -> None:
        self._store = store
        self._artifacts = artifacts

    async def delete_due(self, *, now: datetime, limit: int = 500) -> tuple[str, ...]:
        due = await self._store.list_due(now=now, limit=limit)
        deleted: list[str] = []
        for record in due:
            if record.legal_hold:
                raise PermissionError("trajectory retention source returned a legal-hold record")
            if record.storage_ref is not None:
                await self._artifacts.delete(record.storage_ref)
            await self._store.mark_deleted(record.dataset_id, deleted_at=now)
            deleted.append(record.dataset_id)
        return tuple(deleted)


def trajectory_scope_digest(access_scope: str) -> str:
    if not access_scope.strip():
        raise ValueError("trajectory access_scope MUST be non-empty")
    return hashlib.sha256(access_scope.encode()).hexdigest()


__all__ = [
    "AllowlistTrajectoryAccessAuthorizer",
    "InMemoryTrajectoryDatasetStore",
    "TrajectoryDatasetAdminService",
    "TrajectoryDatasetQuery",
    "TrajectoryRetentionService",
    "trajectory_scope_digest",
]
