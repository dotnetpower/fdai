"""Shadow relational case-history writes with explicit read-authority cutover."""

from __future__ import annotations

from datetime import datetime

from fdai.shared.providers.case_history import CaseHistoryMetadataStore, CaseHistoryRevisionRecord


class DualWriteCaseHistoryMetadataStore:
    def __init__(
        self,
        *,
        authority: CaseHistoryMetadataStore,
        shadow: CaseHistoryMetadataStore,
        read_from_shadow: bool = False,
    ) -> None:
        self._authority = authority
        self._shadow = shadow
        self._reader = shadow if read_from_shadow else authority

    async def append_revision(self, record: CaseHistoryRevisionRecord) -> bool:
        mirrored = await self._shadow.append_revision(record)
        authoritative = await self._authority.append_revision(record)
        if authoritative != mirrored:
            authority_record = await self._authority.latest(
                record.case_id, access_scope_digest=record.access_scope_digest
            )
            shadow_record = await self._shadow.latest(
                record.case_id, access_scope_digest=record.access_scope_digest
            )
            if authority_record != shadow_record:
                raise RuntimeError("case history dual-write divergence")
        return authoritative

    async def latest(
        self, case_id: str, *, access_scope_digest: str
    ) -> CaseHistoryRevisionRecord | None:
        return await self._reader.latest(case_id, access_scope_digest=access_scope_digest)

    async def list_closed(
        self,
        *,
        access_scope_digest: str,
        purpose: str,
        outcome_labels: tuple[str, ...],
        detector_id: str | None = None,
        metric: str | None = None,
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]:
        return await self._reader.list_closed(
            access_scope_digest=access_scope_digest,
            purpose=purpose,
            outcome_labels=outcome_labels,
            detector_id=detector_id,
            metric=metric,
            limit=limit,
        )

    async def list_due(self, *, now: datetime, limit: int) -> tuple[CaseHistoryRevisionRecord, ...]:
        return await self._reader.list_due(now=now, limit=limit)

    async def mark_deletion_started(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        storage_refs: tuple[str, ...],
        started_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        authority = await self._authority.mark_deletion_started(
            case_id,
            access_scope_digest=access_scope_digest,
            revision=revision,
            storage_refs=storage_refs,
            started_at=started_at,
        )
        shadow = await self._shadow.mark_deletion_started(
            case_id,
            access_scope_digest=access_scope_digest,
            revision=revision,
            storage_refs=storage_refs,
            started_at=started_at,
        )
        if authority != shadow:
            raise RuntimeError("case history deletion-intent dual-write divergence")
        return authority

    async def mark_deleted(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        deleted_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        authority = await self._authority.mark_deleted(
            case_id,
            access_scope_digest=access_scope_digest,
            revision=revision,
            deleted_at=deleted_at,
        )
        shadow = await self._shadow.mark_deleted(
            case_id,
            access_scope_digest=access_scope_digest,
            revision=revision,
            deleted_at=deleted_at,
        )
        if authority != shadow:
            raise RuntimeError("case history deletion dual-write divergence")
        return authority


__all__ = ["DualWriteCaseHistoryMetadataStore"]
