"""Backfill legacy StateStore case projections into relational case history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_case_history import PostgresCaseHistoryMetadataStore
from fdai.delivery.persistence.state_store_case_history import deserialize_case_history_record
from fdai.shared.providers.case_history import CaseHistoryArtifactStore, CaseHistoryRevisionRecord

_PREFIX = "case-history:latest:"


@dataclass(frozen=True, slots=True)
class CaseHistoryBackfillReport:
    scanned: int
    migrated: int
    excluded: int
    mismatches: int
    cursor: str | None


@dataclass(frozen=True, slots=True)
class PostgresLegacyCaseReaderConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresLegacyCaseReader:
    def __init__(self, *, config: PostgresLegacyCaseReaderConfig) -> None:
        if not config.dsn:
            raise ValueError("legacy case reader DSN MUST be non-empty")
        self._config = config

    async def page_after(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[CaseHistoryRevisionRecord, ...], str | None]:
        if not 1 <= limit <= 1_000:
            raise ValueError("legacy case page limit MUST be in [1, 1000]")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            result = await connection.execute(
                "SELECT key, value FROM state_kv WHERE key LIKE %s "
                "AND (%s::text IS NULL OR key > %s) ORDER BY key LIMIT %s",
                (f"{_PREFIX}%", cursor, cursor, limit),
            )
            rows = await result.fetchall()
        records = tuple(deserialize_case_history_record(_mapping(row["value"])) for row in rows)
        next_cursor = str(rows[-1]["key"]) if rows else None
        return records, next_cursor


class CaseHistoryBackfillService:
    def __init__(
        self,
        *,
        source: PostgresLegacyCaseReader,
        destination: PostgresCaseHistoryMetadataStore,
        artifacts: CaseHistoryArtifactStore,
    ) -> None:
        self._source = source
        self._destination = destination
        self._artifacts = artifacts

    async def run(
        self,
        *,
        now: datetime,
        page_size: int = 100,
    ) -> CaseHistoryBackfillReport:
        if now.tzinfo is None:
            raise ValueError("case history backfill clock MUST be timezone-aware")
        cursor: str | None = None
        scanned = migrated = excluded = mismatches = 0
        while True:
            records, next_cursor = await self._source.page_after(cursor=cursor, limit=page_size)
            if not records:
                break
            for latest in records:
                scanned += 1
                if latest.deleted_at is not None:
                    await self._destination.backfill_tombstone(latest)
                    migrated += 1
                    continue
                try:
                    await self._backfill_case(latest)
                    migrated += 1
                except (LookupError, ValueError, RuntimeError):
                    mismatches += 1
            cursor = next_cursor
        await self._destination.record_backfill_result(
            mismatch_count=mismatches,
            verified_at=now,
        )
        return CaseHistoryBackfillReport(scanned, migrated, excluded, mismatches, cursor)

    async def _backfill_case(self, latest: CaseHistoryRevisionRecord) -> None:
        revisions = await self._revision_chain(latest)
        for revision in revisions:
            await self._destination.append_revision(revision)
        if latest.deletion_started_at is not None:
            await self._destination.mark_deletion_started(
                latest.case_id,
                access_scope_digest=latest.access_scope_digest,
                revision=latest.revision,
                storage_refs=latest.deletion_storage_refs,
                started_at=latest.deletion_started_at,
            )
        mirrored = await self._destination.latest(
            latest.case_id,
            access_scope_digest=latest.access_scope_digest,
        )
        if mirrored != latest:
            raise RuntimeError("case history backfill parity mismatch")

    async def _revision_chain(
        self,
        latest: CaseHistoryRevisionRecord,
    ) -> tuple[CaseHistoryRevisionRecord, ...]:
        revision = latest.revision
        digest = latest.manifest_digest
        records: list[CaseHistoryRevisionRecord] = []
        while revision >= 1:
            storage_ref = f"case-history/{latest.case_id}/{revision}/{digest}.json"
            content = await self._artifacts.get(storage_ref)
            if content is None or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("case history backfill artifact is unavailable or invalid")
            document = _document(content)
            if (
                document.get("case_id") != latest.case_id
                or document.get("revision") != revision
                or document.get("access_scope_digest") != latest.access_scope_digest
            ):
                raise ValueError("case history backfill artifact identity is invalid")
            source_set_digest = _source_set_digest(document.get("sources"))
            metadata = _metadata(document.get("metadata", {}))
            kind = str(document["kind"])
            operational_outcome = dict(metadata).get("operational_outcome")
            records.append(
                CaseHistoryRevisionRecord(
                    case_id=latest.case_id,
                    revision=revision,
                    kind=kind,
                    correlation_id=str(document["correlation_id"]),
                    purpose=str(document["purpose"]),
                    access_scope_digest=latest.access_scope_digest,
                    manifest_digest=digest,
                    parent_manifest_digest=(
                        str(document["parent_manifest_digest"])
                        if document.get("parent_manifest_digest") is not None
                        else None
                    ),
                    source_set_digest=source_set_digest,
                    storage_ref=storage_ref,
                    artifact_size=len(content),
                    outcome_label=(
                        latest.outcome_label
                        if kind == "prediction"
                        else operational_outcome or latest.outcome_label
                    ),
                    detector_id=latest.detector_id if kind == "prediction" else None,
                    detector_version=latest.detector_version if kind == "prediction" else None,
                    metric=latest.metric if kind == "prediction" else None,
                    event_time_cutoff=_timestamp(document["event_time_cutoff"]),
                    created_by_agent=str(document["created_by_agent"]),
                    sealed_at=_timestamp(document["sealed_at"]),
                    retention_until=latest.retention_until,
                    deletion_due_at=latest.deletion_due_at,
                    metadata=metadata,
                    legal_hold=latest.legal_hold,
                    legal_hold_ref=latest.legal_hold_ref,
                    state_revision=revision,
                )
            )
            parent = document.get("parent_manifest_digest")
            if revision == 1:
                if parent is not None:
                    raise ValueError("case history backfill root has a parent")
                break
            if not isinstance(parent, str) or len(parent) != 64:
                raise ValueError("case history backfill parent is invalid")
            digest = parent
            revision -= 1
        return tuple(reversed(records))


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("legacy case history value MUST be an object")
    return value


def _document(content: bytes) -> dict[str, object]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("case history backfill artifact is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("case history backfill artifact MUST be an object")
    return value


def _source_set_digest(value: object) -> str:
    if not isinstance(value, list) or not value:
        raise ValueError("case history backfill sources are invalid")
    identities: list[str] = []
    for source in value:
        if not isinstance(source, dict):
            raise ValueError("case history backfill source is invalid")
        record_type = str(source.get("record_type") or "")
        record_id = str(source.get("record_id") or "")
        record_digest = str(source.get("record_digest") or "")
        if not record_type or not record_id or len(record_digest) != 64:
            raise ValueError("case history backfill source identity is invalid")
        identities.append(f"{record_type}:{record_id}:{record_digest}")
    return hashlib.sha256("\n".join(sorted(identities)).encode()).hexdigest()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("case history backfill timestamp MUST be an ISO string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("case history backfill timestamp MUST be timezone-aware")
    return result


def _metadata(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("case history backfill metadata MUST be a string mapping")
    return tuple(sorted(value.items()))


__all__ = [
    "CaseHistoryBackfillReport",
    "CaseHistoryBackfillService",
    "PostgresLegacyCaseReader",
    "PostgresLegacyCaseReaderConfig",
]
