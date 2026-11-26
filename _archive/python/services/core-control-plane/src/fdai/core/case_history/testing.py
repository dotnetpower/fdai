"""Deterministic case-history stores for local and unit-test composition."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

from fdai.shared.providers.case_history import CaseHistoryRevisionRecord


class InMemoryCaseHistoryMetadataStore:
    def __init__(self) -> None:
        self._records: dict[str, list[CaseHistoryRevisionRecord]] = {}

    async def append_revision(self, record: CaseHistoryRevisionRecord) -> bool:
        records = self._records.setdefault(record.case_id, [])
        if records and records[0].access_scope_digest != record.access_scope_digest:
            raise PermissionError("case history access scope cannot change")
        if records and records[0].purpose != record.purpose:
            raise ValueError("case history purpose cannot change")
        if records and records[-1].deleted_at is not None:
            raise PermissionError("deleted case history cannot accept revisions")
        if records and records[-1].deletion_started_at is not None:
            raise PermissionError("case history pending deletion cannot accept revisions")
        existing = next((item for item in records if item.revision == record.revision), None)
        if existing is not None:
            if existing != record:
                raise ValueError("case history revision conflict")
            return False
        expected_revision = len(records) + 1
        expected_parent = records[-1].manifest_digest if records else None
        if record.revision != expected_revision or record.parent_manifest_digest != expected_parent:
            raise ValueError("case history revision or parent conflict")
        records.append(record)
        return True

    async def latest(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
    ) -> CaseHistoryRevisionRecord | None:
        records = self._records.get(case_id, [])
        if not records or records[0].access_scope_digest != access_scope_digest:
            return None
        return records[-1]

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
        if not 1 <= limit <= 500:
            raise ValueError("case history list limit MUST be in [1, 500]")
        latest = (records[-1] for records in self._records.values() if records)
        matching = (
            record
            for record in latest
            if record.access_scope_digest == access_scope_digest
            and record.purpose == purpose
            and (detector_id is None or record.detector_id == detector_id)
            and (metric is None or record.metric == metric)
            and record.deleted_at is None
            and record.deletion_started_at is None
            and (not outcome_labels or record.outcome_label in outcome_labels)
        )
        return tuple(
            sorted(matching, key=lambda item: (item.sealed_at, item.case_id), reverse=True)[:limit]
        )

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]:
        if not 1 <= limit <= 5_000:
            raise ValueError("case history retention limit MUST be in [1, 5000]")
        due = (
            records[-1]
            for records in self._records.values()
            if records
            and records[-1].deleted_at is None
            and not records[-1].legal_hold
            and records[-1].deletion_due_at <= now
        )
        return tuple(sorted(due, key=lambda item: (item.deletion_due_at, item.case_id))[:limit])

    async def mark_deletion_started(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        storage_refs: tuple[str, ...],
        started_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        records = self._records.get(case_id)
        if not records or records[-1].access_scope_digest != access_scope_digest:
            raise LookupError("case history was not found")
        current = records[-1]
        if current.legal_hold:
            raise PermissionError("case history is under legal hold")
        if current.revision != revision:
            raise ValueError("case history deletion revision conflict")
        if current.deleted_at is not None:
            return current
        if current.deletion_started_at is not None:
            if current.deletion_storage_refs != storage_refs:
                raise ValueError("case history deletion intent artifact conflict")
            return current
        pending = replace(
            current,
            state_revision=current.state_revision + 1,
            deletion_started_at=started_at,
            deletion_storage_refs=storage_refs,
        )
        records[-1] = pending
        return pending

    async def mark_deleted(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        deleted_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        records = self._records.get(case_id)
        if not records or records[-1].access_scope_digest != access_scope_digest:
            raise LookupError("case history was not found")
        current = records[-1]
        if current.legal_hold:
            raise PermissionError("case history is under legal hold")
        if current.revision != revision:
            raise ValueError("case history deletion revision conflict")
        if current.deleted_at is not None:
            return current
        if current.deletion_started_at is None:
            raise ValueError("case history deletion intent is missing")
        tombstone = replace(
            current,
            storage_ref=None,
            artifact_size=0,
            deleted_at=deleted_at,
            state_revision=current.state_revision + 1,
            deletion_storage_refs=(),
        )
        records[-1] = tombstone
        return tombstone


class InMemoryCaseHistoryArtifactStore:
    def __init__(self) -> None:
        self._records: dict[str, bytes] = {}

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("case history artifact digest mismatch")
        existing = self._records.get(storage_ref)
        if existing is not None:
            if existing != content:
                raise ValueError("case history artifact reference collision")
            return False
        self._records[storage_ref] = bytes(content)
        return True

    async def get(self, storage_ref: str) -> bytes | None:
        return self._records.get(storage_ref)

    async def delete(self, storage_ref: str) -> None:
        self._records.pop(storage_ref, None)


__all__ = [
    "InMemoryCaseHistoryArtifactStore",
    "InMemoryCaseHistoryMetadataStore",
]
