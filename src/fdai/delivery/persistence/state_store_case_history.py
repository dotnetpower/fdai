"""Durable case-history metadata over the existing StateStore CAS contract."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import datetime
from heapq import nsmallest
from itertools import chain

from fdai.shared.providers.case_history import CaseHistoryRevisionRecord
from fdai.shared.providers.state_store import StateStore

_PREFIX = "case-history:latest:"


class StateStoreCaseHistoryMetadataStore:
    """Persist the latest rebuildable case projection with audited CAS."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def append_revision(self, record: CaseHistoryRevisionRecord) -> bool:
        key = _key(record.case_id)
        value = _to_mapping(record)
        audit = _audit_entry(record)
        if record.revision == 1:
            created = await self._store.write_state_with_audit_if_absent(key, value, audit)
            if created:
                return True
        else:
            current_raw = await self._store.read_state(key)
            if current_raw is None:
                raise ValueError("case history revision or parent conflict")
            current = _from_mapping(current_raw)
            duplicate = _validate_transition(current, record)
            if duplicate:
                return False
            updated = await self._store.compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=current.state_revision,
                audit_entry=audit,
            )
            if updated:
                return True
        existing_raw = await self._store.read_state(key)
        if existing_raw is None:
            raise RuntimeError("case history CAS failed without an existing record")
        existing = _from_mapping(existing_raw)
        if _validate_transition(existing, record):
            return False
        raise ValueError("case history compare-and-set lost a concurrent revision")

    async def latest(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
    ) -> CaseHistoryRevisionRecord | None:
        raw = await self._store.read_state(_key(case_id))
        if raw is None:
            return None
        record = _from_mapping(raw)
        if record.access_scope_digest != access_scope_digest:
            return None
        return record

    async def list_closed(
        self,
        *,
        access_scope_digest: str,
        purpose: str,
        outcome_labels: tuple[str, ...],
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("case history list limit MUST be in [1, 500]")
        selected: list[CaseHistoryRevisionRecord] = []
        async for raw_records in self._pages(
            field="access_scope_digest",
            value=access_scope_digest,
        ):
            records = (
                _from_mapping(raw)
                for raw in raw_records
                if raw.get("purpose") == purpose
                and raw.get("deleted_at") is None
                and raw.get("deletion_started_at") is None
                and (not outcome_labels or raw.get("outcome_label") in outcome_labels)
            )
            selected = nsmallest(
                limit,
                chain(selected, records),
                key=lambda item: (-item.sealed_at.timestamp(), item.case_id),
            )
        return tuple(selected)

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[CaseHistoryRevisionRecord, ...]:
        if not 1 <= limit <= 5_000:
            raise ValueError("case history retention limit MUST be in [1, 5000]")
        selected: list[CaseHistoryRevisionRecord] = []
        async for raw_records in self._pages():
            due = (
                _from_mapping(raw)
                for raw in raw_records
                if raw.get("deleted_at") is None
                and raw.get("legal_hold") is not True
                and _timestamp(raw["deletion_due_at"]) <= now
            )
            selected = nsmallest(
                limit,
                chain(selected, due),
                key=lambda item: (item.deletion_due_at, item.case_id),
            )
        return tuple(selected)

    async def _pages(
        self,
        *,
        field: str | None = None,
        value: str | None = None,
    ) -> AsyncIterator[tuple[Mapping[str, object], ...]]:
        offset = 0
        while True:
            page, total = await self._store.read_state_page(
                _PREFIX,
                limit=500,
                offset=offset,
                field=field,
                value=value,
            )
            if not page:
                return
            yield page
            offset += len(page)
            if offset >= total:
                return

    async def mark_deleted(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        deleted_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        key = _key(case_id)
        raw = await self._store.read_state(key)
        if raw is None:
            raise LookupError("case history was not found")
        current = _from_mapping(raw)
        if current.access_scope_digest != access_scope_digest:
            raise LookupError("case history was not found")
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
        updated = await self._store.compare_and_set_state_with_audit(
            key,
            _to_mapping(tombstone),
            expected_revision=current.state_revision,
            audit_entry={
                "event_id": f"case-history-deletion:{case_id}:{revision}",
                "correlation_id": current.correlation_id,
                "idempotency_key": f"case-history-deletion:{case_id}:{revision}",
                "actor": "Muninn",
                "action_kind": "case_history.deleted",
                "mode": "shadow",
                "case_id": case_id,
                "revision": revision,
                "manifest_digest": current.manifest_digest,
                "recorded_at": deleted_at.isoformat(),
            },
        )
        if not updated:
            replay = await self._store.read_state(key)
            if replay is None:
                raise RuntimeError("case history deletion CAS lost its record")
            replay_record = _from_mapping(replay)
            if replay_record.deleted_at is not None:
                return replay_record
            raise ValueError("case history deletion compare-and-set failed")
        return tombstone

    async def mark_deletion_started(
        self,
        case_id: str,
        *,
        access_scope_digest: str,
        revision: int,
        storage_refs: tuple[str, ...],
        started_at: datetime,
    ) -> CaseHistoryRevisionRecord:
        key = _key(case_id)
        raw = await self._store.read_state(key)
        if raw is None:
            raise LookupError("case history was not found")
        current = _from_mapping(raw)
        if current.access_scope_digest != access_scope_digest:
            raise LookupError("case history was not found")
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
        updated = await self._store.compare_and_set_state_with_audit(
            key,
            _to_mapping(pending),
            expected_revision=current.state_revision,
            audit_entry={
                "event_id": f"case-history-deletion-started:{case_id}:{revision}",
                "correlation_id": current.correlation_id,
                "idempotency_key": f"case-history-deletion-started:{case_id}:{revision}",
                "actor": "Muninn",
                "action_kind": "case_history.deletion_started",
                "mode": "shadow",
                "case_id": case_id,
                "revision": revision,
                "manifest_digest": current.manifest_digest,
                "recorded_at": started_at.isoformat(),
            },
        )
        if updated:
            return pending
        replay = await self._store.read_state(key)
        if replay is None:
            raise RuntimeError("case history deletion intent CAS lost its record")
        replay_record = _from_mapping(replay)
        if (
            replay_record.revision == revision
            and replay_record.deletion_started_at is not None
            and replay_record.deletion_storage_refs == storage_refs
        ):
            return replay_record
        raise ValueError("case history deletion intent compare-and-set failed")


def _key(case_id: str) -> str:
    return f"{_PREFIX}{case_id}"


def _validate_transition(
    existing: CaseHistoryRevisionRecord,
    incoming: CaseHistoryRevisionRecord,
) -> bool:
    if existing.access_scope_digest != incoming.access_scope_digest:
        raise PermissionError("case history access scope cannot change")
    if existing.purpose != incoming.purpose:
        raise ValueError("case history purpose cannot change")
    if existing.deleted_at is not None:
        raise PermissionError("deleted case history cannot accept revisions")
    if existing.deletion_started_at is not None:
        raise PermissionError("case history pending deletion cannot accept revisions")
    if existing.source_set_digest == incoming.source_set_digest:
        if existing != incoming:
            raise ValueError("case history source set was reused with different metadata")
        return True
    if (
        incoming.revision != existing.revision + 1
        or incoming.state_revision != existing.state_revision + 1
        or incoming.parent_manifest_digest != existing.manifest_digest
    ):
        raise ValueError("case history revision or parent conflict")
    return False


def _audit_entry(record: CaseHistoryRevisionRecord) -> dict[str, object]:
    return {
        "event_id": f"case-history:{record.case_id}:{record.revision}",
        "correlation_id": record.correlation_id,
        "idempotency_key": f"case-history:{record.case_id}:{record.source_set_digest}",
        "actor": record.created_by_agent,
        "action_kind": "case_history.revision.sealed",
        "mode": "shadow",
        "case_id": record.case_id,
        "revision": record.revision,
        "manifest_digest": record.manifest_digest,
        "outcome_label": record.outcome_label,
        "recorded_at": record.sealed_at.isoformat(),
    }


def _to_mapping(record: CaseHistoryRevisionRecord) -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "case_id": record.case_id,
        "revision": record.state_revision,
        "case_revision": record.revision,
        "kind": record.kind,
        "correlation_id": record.correlation_id,
        "purpose": record.purpose,
        "access_scope_digest": record.access_scope_digest,
        "manifest_digest": record.manifest_digest,
        "parent_manifest_digest": record.parent_manifest_digest,
        "source_set_digest": record.source_set_digest,
        "storage_ref": record.storage_ref,
        "artifact_size": record.artifact_size,
        "outcome_label": record.outcome_label,
        "detector_id": record.detector_id,
        "detector_version": record.detector_version,
        "metric": record.metric,
        "event_time_cutoff": record.event_time_cutoff.isoformat(),
        "created_by_agent": record.created_by_agent,
        "sealed_at": record.sealed_at.isoformat(),
        "retention_until": record.retention_until.isoformat(),
        "deletion_due_at": record.deletion_due_at.isoformat(),
        "legal_hold": record.legal_hold,
        "legal_hold_ref": record.legal_hold_ref,
        "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
        "deletion_started_at": (
            record.deletion_started_at.isoformat() if record.deletion_started_at else None
        ),
        "deletion_storage_refs": list(record.deletion_storage_refs),
    }


def _from_mapping(raw: Mapping[str, object]) -> CaseHistoryRevisionRecord:
    schema_version = raw.get("schema_version")
    if schema_version not in {"1.0.0", "1.1.0"}:
        raise ValueError("unsupported case history metadata schema")
    legacy = schema_version == "1.0.0"
    return CaseHistoryRevisionRecord(
        case_id=str(raw["case_id"]),
        revision=int(str(raw["revision"] if legacy else raw["case_revision"])),
        kind=str(raw["kind"]),
        correlation_id=str(raw["correlation_id"]),
        purpose=str(raw["purpose"]),
        access_scope_digest=str(raw["access_scope_digest"]),
        manifest_digest=str(raw["manifest_digest"]),
        parent_manifest_digest=(
            str(raw["parent_manifest_digest"])
            if raw.get("parent_manifest_digest") is not None
            else None
        ),
        source_set_digest=str(raw["source_set_digest"]),
        storage_ref=(str(raw["storage_ref"]) if raw.get("storage_ref") is not None else None),
        artifact_size=int(str(raw["artifact_size"])),
        outcome_label=str(raw["outcome_label"]),
        detector_id=str(raw["detector_id"]),
        detector_version=str(raw["detector_version"]),
        metric=str(raw["metric"]),
        event_time_cutoff=_timestamp(raw["event_time_cutoff"]),
        created_by_agent=str(raw["created_by_agent"]),
        sealed_at=_timestamp(raw["sealed_at"]),
        retention_until=_timestamp(raw["retention_until"]),
        deletion_due_at=_timestamp(raw["deletion_due_at"]),
        legal_hold=bool(raw.get("legal_hold", False)),
        legal_hold_ref=(str(raw["legal_hold_ref"]) if raw.get("legal_hold_ref") else None),
        deleted_at=(_timestamp(raw["deleted_at"]) if raw.get("deleted_at") is not None else None),
        state_revision=int(str(raw["revision"])),
        deletion_started_at=(
            _timestamp(raw["deletion_started_at"])
            if raw.get("deletion_started_at") is not None
            else None
        ),
        deletion_storage_refs=_string_tuple(raw.get("deletion_storage_refs", ())),
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("case history timestamp MUST be an ISO string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError("case history deletion refs MUST be non-empty strings")
    return tuple(value)


__all__ = ["StateStoreCaseHistoryMetadataStore"]
