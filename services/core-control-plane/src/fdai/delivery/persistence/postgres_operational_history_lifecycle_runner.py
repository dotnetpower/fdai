"""PostgreSQL evidence access for the operational-history lifecycle Job."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveSourcePartition,
    ArchiveVerificationReceipt,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveRestoreReceipt,
    RetentionHold,
    RetentionHoldKind,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationPartition,
    ObservationPartitionKind,
    ObservationPartitionPin,
    ObservationPartitionState,
    ObservationPinKind,
    build_observation_checkpoint,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureAssessment,
    StoragePressurePolicy,
    assess_storage_pressure,
)
from fdai.core.ontology_platform.operational_history_retention import (
    RetentionDeletionMethod,
)

_STORAGE_RELATIONS = (
    "inventory_observation_journal",
    "inventory_observation_lifecycle_binding",
    "inventory_observation_partition",
    "inventory_observation_checkpoint",
    "operational_archive_artifact",
)
_CAMPAIGN_ID_PATTERN = re.compile(r"^certify-history-[0-9a-f]{48}$")
_SYNTHETIC_SCOPE_PATTERN = re.compile(r"^synthetic/oi16-certification/[0-9a-f]{48}$")


@dataclass(frozen=True, slots=True)
class ScopeStorageSample:
    """One bounded physical measurement of an observation scope's footprint."""

    table_bytes: int
    index_bytes: int
    wal_bytes: int
    partition_count: int
    purge_backlog: int
    change_count: int

    def __post_init__(self) -> None:
        if (
            min(
                self.table_bytes,
                self.index_bytes,
                self.wal_bytes,
                self.partition_count,
                self.purge_backlog,
                self.change_count,
            )
            < 0
        ):
            raise ValueError("operational history storage measurements MUST NOT be negative")

    def record(self) -> dict[str, int]:
        """Return the sanitized numeric body used as bounded storage evidence."""

        return {
            "table_bytes": self.table_bytes,
            "index_bytes": self.index_bytes,
            "wal_bytes": self.wal_bytes,
            "partition_count": self.partition_count,
            "purge_backlog": self.purge_backlog,
            "change_count": self.change_count,
        }


class PostgresOperationalHistoryLifecycleRepository:
    """Read lifecycle evidence and commit exact monotonic state transitions."""

    def __init__(self, *, dsn: str, statement_timeout_ms: int = 30_000) -> None:
        if not dsn:
            raise ValueError("operational history lifecycle DSN MUST NOT be empty")
        if statement_timeout_ms < 1:
            raise ValueError("operational history lifecycle statement timeout MUST be positive")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms

    async def assess_pressure(self, policy: StoragePressurePolicy) -> StoragePressureAssessment:
        row = await self._one(
            "SELECT pg_database_size(current_database()) AS database_bytes, "
            "COUNT(*) FILTER (WHERE state='purge_eligible') AS purge_backlog, "
            "COALESCE((SELECT GREATEST(0, "
            "(value->>'journal_high_watermark')::bigint - "
            "(value->>'ontology_projection_watermark')::bigint) "
            "FROM state_kv WHERE key='inventory-observation:watermarks'), 0) "
            "AS projection_lag FROM inventory_observation_partition",
            (),
        )
        return assess_storage_pressure(
            policy,
            database_bytes=int(row["database_bytes"]),
            purge_backlog=int(row["purge_backlog"]),
            projection_lag=int(row["projection_lag"]),
            growth_bytes_per_second=0,
        )

    async def list_partitions(
        self, *, limit: int, now: datetime, scope_ref: str | None = None
    ) -> tuple[ObservationPartition, ...]:
        """List retained partitions, optionally restricted to one exact scope.

        ``scope_ref`` filters inside the query rather than after the ``LIMIT``. A
        caller that owns a bounded scope would otherwise have its own rows crowded
        out of the result by unrelated partitions and would read that crowding as
        missing evidence.
        """

        rows = await self._all(
            "SELECT partition_id, scope_ref, interval_start, interval_end, "
            "first_watermark, last_watermark, partition_kind, state, correction_of, "
            "retention_policy_digest, created_at FROM inventory_observation_partition "
            "WHERE state <> 'purged' AND (state <> 'open' OR interval_end <= %s) "
            "AND (%s::text IS NULL OR scope_ref = %s) "
            "ORDER BY interval_start, partition_id LIMIT %s",
            (now, scope_ref, scope_ref, limit),
        )
        return tuple(_partition(row) for row in rows)

    async def measure_scope_storage(self, *, scope_ref: str) -> ScopeStorageSample:
        """Measure the bounded physical footprint one observation scope occupies.

        Table and index bytes are read per relation rather than from the whole
        database, so an unrelated table cannot make a synthetic scope look bounded or
        unbounded. The write-ahead log position is a database-wide counter: it is
        reported as an absolute byte offset so a caller can difference two samples
        and bound the log a replay actually produced.
        """

        if not scope_ref:
            raise ValueError("operational history storage scope MUST NOT be empty")
        row = await self._one(
            "SELECT "
            "COALESCE(SUM(pg_table_size(relation.oid)), 0) AS table_bytes, "
            "COALESCE(SUM(pg_indexes_size(relation.oid)), 0) AS index_bytes "
            "FROM unnest(%s::text[]) AS name "
            "JOIN pg_class AS relation ON relation.relname = name "
            "JOIN pg_namespace AS space ON space.oid = relation.relnamespace "
            "AND space.nspname = 'public'",
            (list(_STORAGE_RELATIONS),),
        )
        wal = await self._one(
            "SELECT pg_wal_lsn_diff(CASE WHEN pg_is_in_recovery() "
            "THEN pg_last_wal_replay_lsn() ELSE pg_current_wal_lsn() END, '0/0')::bigint "
            "AS wal_bytes",
            (),
        )
        scope = await self._one(
            "SELECT COUNT(*) AS partition_count, "
            "COUNT(*) FILTER (WHERE state='purge_eligible') AS purge_backlog, "
            "COALESCE((SELECT COUNT(*) FROM inventory_observation_lifecycle_binding AS binding "
            "JOIN inventory_observation_partition AS owned "
            "ON owned.partition_id=binding.partition_id "
            "WHERE owned.scope_ref=%s), 0) AS change_count "
            "FROM inventory_observation_partition WHERE scope_ref=%s",
            (scope_ref, scope_ref),
        )
        return ScopeStorageSample(
            table_bytes=int(row["table_bytes"]),
            index_bytes=int(row["index_bytes"]),
            wal_bytes=int(wal["wal_bytes"]),
            partition_count=int(scope["partition_count"]),
            purge_backlog=int(scope["purge_backlog"]),
            change_count=int(scope["change_count"]),
        )

    async def latest_checkpoint(self, partition_id: str) -> ObservationCheckpoint | None:
        row = await self._optional_one(
            "SELECT record FROM inventory_observation_checkpoint "
            "WHERE partition_id=%s ORDER BY created_at DESC, checkpoint_id DESC LIMIT 1",
            (partition_id,),
        )
        return None if row is None else _checkpoint(_mapping(row["record"]))

    async def latest_manifest(self, partition_id: str) -> ArchiveManifest | None:
        row = await self._optional_one(
            "SELECT manifest.record FROM operational_archive_manifest AS manifest "
            "WHERE manifest.record->'source_partitions' @> %s::jsonb "
            "ORDER BY manifest.created_at DESC LIMIT 1",
            (Jsonb([{"partition_id": partition_id}]),),
        )
        return None if row is None else _manifest(_mapping(row["record"]))

    async def latest_manifest_by_digest(self, manifest_digest: str) -> ArchiveManifest | None:
        """Return one exact archive manifest by its content-addressed identity."""

        if not manifest_digest:
            raise ValueError("archive manifest digest MUST NOT be empty")
        row = await self._optional_one(
            "SELECT record FROM operational_archive_manifest WHERE manifest_digest=%s",
            (manifest_digest,),
        )
        return None if row is None else _manifest(_mapping(row["record"]))

    async def latest_verification(self, manifest_digest: str) -> ArchiveVerificationReceipt | None:
        row = await self._optional_one(
            "SELECT record FROM operational_archive_verification_receipt "
            "WHERE manifest_digest=%s ORDER BY verified_at DESC, receipt_digest DESC LIMIT 1",
            (manifest_digest,),
        )
        return None if row is None else _verification(_mapping(row["record"]))

    async def latest_restore(self, manifest_digest: str) -> ArchiveRestoreReceipt | None:
        row = await self._optional_one(
            "SELECT record FROM operational_archive_restore_receipt "
            "WHERE manifest_digest=%s ORDER BY sampled_at DESC, receipt_digest DESC LIMIT 1",
            (manifest_digest,),
        )
        return None if row is None else _restore(_mapping(row["record"]))

    async def active_pins(
        self, partition_id: str, *, now: datetime
    ) -> tuple[ObservationPartitionPin, ...]:
        rows = await self._all(
            "SELECT DISTINCT ON (pin_id) record FROM inventory_observation_partition_pin_event "
            "WHERE partition_id=%s ORDER BY pin_id, COALESCE(released_at, placed_at) DESC, "
            "pin_event_id DESC",
            (partition_id,),
        )
        pins = tuple(_pin(_mapping(row["record"])) for row in rows)
        return tuple(
            pin
            for pin in pins
            if pin.released_at is None and (pin.expires_at is None or now < pin.expires_at)
        )

    async def retention_permitted(self, partition: ObservationPartition, *, now: datetime) -> bool:
        if partition.state is not ObservationPartitionState.PURGE_ELIGIBLE:
            return True
        row = await self._one(
            "SELECT warm_retention_seconds, deletion_method, review_at "
            "FROM operational_retention_policy WHERE policy_digest=%s",
            (partition.retention_policy_digest,),
        )
        warm_end = partition.interval_end + timedelta(seconds=int(row["warm_retention_seconds"]))
        return (
            str(row["deletion_method"]) == RetentionDeletionMethod.PARTITION_PURGE.value
            and now >= warm_end
            and now < _time(row["review_at"])
        )

    async def active_holds(
        self, manifest_digest: str, *, now: datetime
    ) -> tuple[RetentionHold, ...]:
        rows = await self._all(
            "SELECT DISTINCT ON (hold_id) hold_id, hold_kind, starts_at, ends_at, event_type "
            "FROM operational_retention_hold_event WHERE manifest_digest=%s "
            "ORDER BY hold_id, recorded_at DESC, event_digest DESC",
            (manifest_digest,),
        )
        return tuple(
            RetentionHold(
                hold_id=str(row["hold_id"]),
                manifest_digest=manifest_digest,
                kind=RetentionHoldKind(str(row["hold_kind"])),
                starts_at=_time(row["starts_at"]),
                ends_at=None if row["ends_at"] is None else _time(row["ends_at"]),
            )
            for row in rows
            if row["event_type"] != "released"
            and _time(row["starts_at"]) <= now
            and (row["ends_at"] is None or now < _time(row["ends_at"]))
        )

    async def build_checkpoint(
        self, partition: ObservationPartition, *, now: datetime
    ) -> ObservationCheckpoint:
        records = await self._journal_records(partition.partition_id)
        manifest_row = await self._optional_one(
            "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'",
            (),
        )
        manifest = {} if manifest_row is None else _mapping(manifest_row["value"])
        projection_watermark = _integer(manifest.get("projection_high_watermark"), default=0)
        ontology_digest = str(manifest.get("ontology_release_digest", ""))
        graph_digest = str(manifest.get("manifest_digest", ""))
        source_digest = _json_digest(records)
        schema_digest = _json_digest(
            sorted({str(item.get("schema_version", "")) for item in records})
        )
        valid = (
            bool(records)
            and manifest.get("complete") is True
            and projection_watermark >= partition.last_watermark
            and _is_digest(ontology_digest)
            and _is_digest(graph_digest)
        )
        return build_observation_checkpoint(
            partition_id=partition.partition_id,
            first_watermark=partition.first_watermark,
            last_watermark=partition.last_watermark,
            scope_ref=partition.scope_ref,
            object_count=sum(1 for item in records if item.get("subject_kind") == "object"),
            relationship_count=sum(
                1 for item in records if item.get("subject_kind") == "relationship"
            ),
            property_count=sum(_property_count(item) for item in records),
            source_digest=source_digest,
            schema_digest=schema_digest,
            ontology_release_digest=(
                ontology_digest if _is_digest(ontology_digest) else source_digest
            ),
            projection_digest=(graph_digest if _is_digest(graph_digest) else source_digest),
            projection_watermark=max(partition.last_watermark, projection_watermark),
            graph_digest=graph_digest if _is_digest(graph_digest) else source_digest,
            missing_count=sum(item.get("properties_complete") is not True for item in records),
            quarantined_count=0,
            conflicted_count=0,
            tombstoned_count=sum(item.get("observation_kind") == "tombstone" for item in records),
            valid=valid,
            created_at=now,
        )

    async def archive_records(self, partition_id: str) -> tuple[Mapping[str, object], ...]:
        return tuple(await self._journal_records(partition_id))

    async def restore_recovery_records(
        self,
        *,
        campaign_id: str,
        scope_ref: str,
        partition_id: str,
        records: Sequence[Mapping[str, object]],
        recovered_at: datetime,
    ) -> tuple[Mapping[str, object], ...]:
        """Restore bounded synthetic archive records into the isolated recovery table."""

        if (
            _CAMPAIGN_ID_PATTERN.fullmatch(campaign_id) is None
            or _SYNTHETIC_SCOPE_PATTERN.fullmatch(scope_ref) is None
            or not _is_digest(partition_id)
            or not 1 <= len(records) <= 64
        ):
            raise ValueError("operational history recovery rehearsal is outside its bound")
        rows: list[tuple[object, ...]] = []
        for record in records:
            observation_id = str(record.get("observation_id", ""))
            content_digest = str(record.get("content_digest", ""))
            if (
                str(record.get("scope_ref", "")) != scope_ref
                or not _is_digest(observation_id)
                or not _is_digest(content_digest)
            ):
                raise ValueError("operational history recovery record is not synthetic and exact")
            rows.append(
                (
                    campaign_id,
                    scope_ref,
                    partition_id,
                    observation_id,
                    content_digest,
                    Jsonb(dict(record)),
                    recovered_at,
                )
            )
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            for row in rows:
                await connection.execute(
                    "INSERT INTO operational_history_recovery_rehearsal "
                    "(campaign_id, scope_ref, partition_id, observation_id, content_digest, "
                    "record, recovered_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (campaign_id, observation_id) DO NOTHING",
                    row,
                )
            cursor = await connection.execute(
                "SELECT record FROM operational_history_recovery_rehearsal "
                "WHERE campaign_id=%s AND partition_id=%s "
                "ORDER BY observation_id LIMIT 64",
                (campaign_id, partition_id),
            )
            restored = await cursor.fetchall()
        return tuple(_mapping(row["record"]) for row in restored)

    async def transition(
        self,
        partition: ObservationPartition,
        target: ObservationPartitionState,
        *,
        reason: str,
        evidence_refs: tuple[str, ...],
        recorded_at: datetime,
    ) -> None:
        body = {
            "partition_id": partition.partition_id,
            "prior_state": partition.state.value,
            "resulting_state": target.value,
            "reason_code": reason,
            "evidence_refs": list(evidence_refs),
            "recorded_at": recorded_at.astimezone(UTC).isoformat(),
        }
        event_id = _json_digest(body)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (partition.partition_id,),
            )
            cursor = await connection.execute(
                "UPDATE inventory_observation_partition SET state=%s, updated_at=%s "
                "WHERE partition_id=%s AND state=%s RETURNING partition_id",
                (
                    target.value,
                    recorded_at,
                    partition.partition_id,
                    partition.state.value,
                ),
            )
            if await cursor.fetchone() is None:
                raise RuntimeError("operational history partition state changed concurrently")
            await connection.execute(
                "INSERT INTO inventory_observation_partition_event "
                "(event_id, partition_id, prior_state, resulting_state, reason_code, "
                "evidence_refs, recorded_at, record) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (event_id) DO NOTHING",
                (
                    event_id,
                    partition.partition_id,
                    partition.state.value,
                    target.value,
                    reason,
                    list(evidence_refs),
                    recorded_at,
                    Jsonb({**body, "event_id": event_id}),
                ),
            )

    async def _journal_records(self, partition_id: str) -> list[dict[str, object]]:
        rows = await self._all(
            "SELECT to_jsonb(journal) - 'watermark' AS record "
            "FROM inventory_observation_journal AS journal "
            "JOIN inventory_observation_lifecycle_binding AS binding "
            "ON binding.observation_id=journal.observation_id "
            "WHERE binding.partition_id=%s ORDER BY journal.watermark",
            (partition_id,),
        )
        return [_mapping(row["record"]) for row in rows]

    async def _one(self, query: str, parameters: tuple[object, ...]) -> dict[str, Any]:
        row = await self._optional_one(query, parameters)
        if row is None:
            raise LookupError("operational history lifecycle evidence is unavailable")
        return row

    async def _optional_one(
        self, query: str, parameters: tuple[object, ...]
    ) -> dict[str, Any] | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(query, parameters)
            return await cursor.fetchone()

    async def _all(self, query: str, parameters: tuple[object, ...]) -> list[dict[str, Any]]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(query, parameters)
            return list(await cursor.fetchall())

    async def _set_timeout(self, connection: psycopg.AsyncConnection[dict[str, Any]]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(self._statement_timeout_ms),),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=10,
        )


def _partition(row: Mapping[str, object]) -> ObservationPartition:
    return ObservationPartition(
        partition_id=str(row["partition_id"]),
        scope_ref=str(row["scope_ref"]),
        interval_start=_time(row["interval_start"]),
        interval_end=_time(row["interval_end"]),
        first_watermark=_integer(row["first_watermark"]),
        last_watermark=_integer(row["last_watermark"]),
        kind=ObservationPartitionKind(str(row["partition_kind"])),
        state=ObservationPartitionState(str(row["state"])),
        correction_of=None if row["correction_of"] is None else str(row["correction_of"]),
        retention_policy_digest=str(row["retention_policy_digest"]),
        created_at=_time(row["created_at"]),
        digest=str(row["partition_id"]),
    )


def _checkpoint(raw: Mapping[str, object]) -> ObservationCheckpoint:
    values = dict(raw)
    values["created_at"] = _time(values["created_at"])
    return ObservationCheckpoint(**values)  # type: ignore[arg-type]


def _manifest(raw: Mapping[str, object]) -> ArchiveManifest:
    partitions = tuple(
        ArchiveSourcePartition(
            partition_id=str(item["partition_id"]),
            content_digest=str(item["content_digest"]),
            interval_start=_time(item["interval_start"]),
            interval_end=_time(item["interval_end"]),
            object_count=_integer(item["object_count"]),
            relationship_count=_integer(item["relationship_count"]),
            schema_version=str(item["schema_version"]),
            ontology_release_digest=str(item["ontology_release_digest"]),
            complete=bool(item["complete"]),
            conflict_count=_integer(item.get("conflict_count", 0)),
        )
        for item in _mapping_sequence(raw.get("source_partitions"))
    )
    return ArchiveManifest(
        schema_version=str(raw["schema_version"]),
        source_partitions=partitions,
        covered_start=_time(raw["covered_start"]),
        covered_end=_time(raw["covered_end"]),
        object_count=_integer(raw["object_count"]),
        relationship_count=_integer(raw["relationship_count"]),
        source_schema_versions=_string_tuple(raw["source_schema_versions"]),
        ontology_release_digests=_string_tuple(raw["ontology_release_digests"]),
        archive_content_digest=str(raw["archive_content_digest"]),
        compression_profile=str(raw["compression_profile"]),
        encryption_profile=str(raw["encryption_profile"]),
        destination_class=str(raw["destination_class"]),
        retention_class=str(raw["retention_class"]),
        creation_receipt_digest=str(raw["creation_receipt_digest"]),
        created_at=_time(raw["created_at"]),
        coverage_complete=bool(raw["coverage_complete"]),
        digest=str(raw["digest"]),
    )


def _verification(raw: Mapping[str, object]) -> ArchiveVerificationReceipt:
    return ArchiveVerificationReceipt(
        manifest_digest=str(raw["manifest_digest"]),
        verified=bool(raw["verified"]),
        reason_codes=_string_tuple(raw["reason_codes"]),
        verified_at=_time(raw["verified_at"]),
        digest=str(raw["digest"]),
    )


def _restore(raw: Mapping[str, object]) -> ArchiveRestoreReceipt:
    return ArchiveRestoreReceipt(
        manifest_digest=str(raw["manifest_digest"]),
        verification_receipt_digest=str(raw["verification_receipt_digest"]),
        sampled_partition_digests=_string_tuple(raw["sampled_partition_digests"]),
        restored_object_count=_integer(raw["restored_object_count"]),
        restored_relationship_count=_integer(raw["restored_relationship_count"]),
        passed=bool(raw["passed"]),
        reason_codes=_string_tuple(raw["reason_codes"]),
        sampled_at=_time(raw["sampled_at"]),
        digest=str(raw["digest"]),
    )


def _pin(raw: Mapping[str, object]) -> ObservationPartitionPin:
    return ObservationPartitionPin(
        pin_event_id=str(raw["pin_event_id"]),
        pin_id=str(raw["pin_id"]),
        partition_id=str(raw["partition_id"]),
        kind=ObservationPinKind(str(raw["pin_kind"])),
        case_ref=str(raw["case_ref"]),
        placed_at=_time(raw["placed_at"]),
        released_at=None if raw.get("released_at") is None else _time(raw["released_at"]),
        expires_at=None if raw.get("expires_at") is None else _time(raw["expires_at"]),
        evidence_refs=_string_tuple(raw["evidence_refs"]),
        digest=str(raw["digest"]),
    )


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("operational history lifecycle record MUST be an object")
    return dict(value)


def _mapping_sequence(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError("operational history lifecycle record array is invalid")
    return tuple(dict(item) for item in value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("operational history lifecycle string array is invalid")
    return tuple(str(item) for item in value)


def _time(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("operational history lifecycle timestamp MUST be timezone-aware")
    return parsed


def _property_count(record: Mapping[str, object]) -> int:
    properties = record.get("properties")
    return len(properties) if isinstance(properties, Mapping) else 0


def _integer(value: object, *, default: int | None = None) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if default is not None:
        return default
    raise ValueError("operational history lifecycle integer is invalid")


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _is_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = ["PostgresOperationalHistoryLifecycleRepository", "ScopeStorageSample"]
