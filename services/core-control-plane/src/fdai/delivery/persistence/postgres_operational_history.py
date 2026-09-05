"""PostgreSQL persistence for operational observation lifecycle evidence."""

# ruff: noqa: S608 - table and identifier names are private fixed call-site literals.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryCertificationReceipt,
    certification_record,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationCorrectionReceipt,
    ObservationPartition,
    ObservationPartitionPin,
    ResourceIncarnation,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureAssessment,
)
from fdai.core.ontology_platform.operational_history_retention import (
    ObservationRetentionPolicy,
)
from fdai.delivery.operational_history_archive import OperationalArchiveArtifact


@dataclass(frozen=True, slots=True)
class PostgresOperationalHistoryConfig:
    """PostgreSQL connection bounds for lifecycle evidence."""

    dsn: str
    statement_timeout_ms: int = 30_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("operational history DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("operational history PostgreSQL timeouts MUST be positive")


class PostgresOperationalHistoryStore:
    """Persist lifecycle records with content-bound replay checks."""

    def __init__(self, *, config: PostgresOperationalHistoryConfig) -> None:
        self._config = config

    async def put_retention_policy(
        self,
        policy: ObservationRetentionPolicy,
        *,
        recorded_at: datetime,
    ) -> bool:
        record = _policy_record(policy)
        return await self._put(
            table="operational_retention_policy",
            id_column="policy_digest",
            identifier=policy.digest,
            record=record,
            query=(
                "INSERT INTO operational_retention_policy "
                "(policy_digest, policy_id, fact_family, purpose, hot_retention_seconds, "
                "warm_retention_seconds, archive_class, deletion_method, review_at, "
                "record, recorded_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (policy_digest) DO NOTHING RETURNING policy_digest"
            ),
            values=(
                policy.digest,
                policy.policy_id,
                policy.fact_family,
                policy.purpose,
                policy.hot_retention_seconds,
                policy.warm_retention_seconds,
                policy.archive_class,
                policy.deletion_method.value,
                policy.review_at,
                Jsonb(record),
                recorded_at,
            ),
        )

    async def put_incarnation(self, incarnation: ResourceIncarnation) -> bool:
        record = _incarnation_record(incarnation)
        return await self._put(
            table="inventory_resource_incarnation",
            id_column="incarnation_id",
            identifier=incarnation.incarnation_id,
            record=record,
            query=(
                "INSERT INTO inventory_resource_incarnation "
                "(incarnation_id, resource_ref, resource_type, provider_identity, "
                "lifecycle_boundary_ref, opened_at, closed_at, opening_observation_id, "
                "closing_observation_id, record) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (incarnation_id) DO NOTHING RETURNING incarnation_id"
            ),
            values=(
                incarnation.incarnation_id,
                incarnation.resource_ref,
                incarnation.resource_type,
                incarnation.provider_identity,
                incarnation.lifecycle_boundary_ref,
                incarnation.opened_at,
                incarnation.closed_at,
                incarnation.opening_observation_id,
                incarnation.closing_observation_id,
                Jsonb(record),
            ),
        )

    async def put_partition(self, partition: ObservationPartition) -> bool:
        record = _partition_record(partition)
        return await self._put(
            table="inventory_observation_partition",
            id_column="partition_id",
            identifier=partition.partition_id,
            record=record,
            query=(
                "INSERT INTO inventory_observation_partition "
                "(partition_id, scope_ref, interval_start, interval_end, first_watermark, "
                "last_watermark, partition_kind, state, correction_of, "
                "retention_policy_digest, record, created_at, updated_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (partition_id) DO NOTHING RETURNING partition_id"
            ),
            values=(
                partition.partition_id,
                partition.scope_ref,
                partition.interval_start,
                partition.interval_end,
                partition.first_watermark,
                partition.last_watermark,
                partition.kind.value,
                partition.state.value,
                partition.correction_of,
                partition.retention_policy_digest,
                Jsonb(record),
                partition.created_at,
                partition.created_at,
            ),
        )

    async def append_checkpoint(self, checkpoint: ObservationCheckpoint) -> bool:
        record = _checkpoint_record(checkpoint)
        return await self._put(
            table="inventory_observation_checkpoint",
            id_column="checkpoint_id",
            identifier=checkpoint.checkpoint_id,
            record=record,
            query=(
                "INSERT INTO inventory_observation_checkpoint "
                "(checkpoint_id, partition_id, first_watermark, last_watermark, "
                "projection_watermark, valid, record, created_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (checkpoint_id) DO NOTHING RETURNING checkpoint_id"
            ),
            values=(
                checkpoint.checkpoint_id,
                checkpoint.partition_id,
                checkpoint.first_watermark,
                checkpoint.last_watermark,
                checkpoint.projection_watermark,
                checkpoint.valid,
                Jsonb(record),
                checkpoint.created_at,
            ),
        )

    async def append_pin(self, pin: ObservationPartitionPin) -> bool:
        record = _pin_record(pin)
        return await self._put(
            table="inventory_observation_partition_pin_event",
            id_column="pin_event_id",
            identifier=pin.pin_event_id,
            record=record,
            query=(
                "INSERT INTO inventory_observation_partition_pin_event "
                "(pin_event_id, pin_id, partition_id, pin_kind, case_ref, placed_at, "
                "released_at, expires_at, evidence_refs, record) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (pin_event_id) DO NOTHING RETURNING pin_event_id"
            ),
            values=(
                pin.pin_event_id,
                pin.pin_id,
                pin.partition_id,
                pin.kind.value,
                pin.case_ref,
                pin.placed_at,
                pin.released_at,
                pin.expires_at,
                list(pin.evidence_refs),
                Jsonb(record),
            ),
        )

    async def resolve_evidence_partitions(
        self,
        evidence_refs: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve observation evidence to exact retained partition identities."""

        if not evidence_refs or len(evidence_refs) > 256:
            raise ValueError("operational history evidence reference set is outside its bound")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT DISTINCT partition_id "
                "FROM inventory_observation_lifecycle_binding "
                "WHERE observation_id=ANY(%s::text[]) ORDER BY partition_id",
                (list(evidence_refs),),
            )
            rows = await cursor.fetchall()
        return tuple(str(row["partition_id"]) for row in rows)

    async def append_correction(self, receipt: ObservationCorrectionReceipt) -> bool:
        record = _correction_record(receipt)
        return await self._put(
            table="inventory_observation_correction_receipt",
            id_column="receipt_id",
            identifier=receipt.receipt_id,
            record=record,
            query=(
                "INSERT INTO inventory_observation_correction_receipt "
                "(receipt_id, correction_partition_id, projection_watermark, complete, "
                "record, closed_at) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (receipt_id) DO NOTHING RETURNING receipt_id"
            ),
            values=(
                receipt.receipt_id,
                receipt.correction_partition_id,
                receipt.projection_watermark,
                receipt.complete,
                Jsonb(record),
                receipt.closed_at,
            ),
        )

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool:
        record = _artifact_record(artifact)
        return await self._put(
            table="operational_archive_artifact",
            id_column="artifact_digest",
            identifier=artifact.artifact_digest,
            record=record,
            query=(
                "INSERT INTO operational_archive_artifact "
                "(artifact_digest, storage_ref, manifest_digest, scope_refs, "
                "allowed_purposes, byte_count, record, created_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (artifact_digest) DO NOTHING RETURNING artifact_digest"
            ),
            values=(
                artifact.artifact_digest,
                artifact.storage_ref,
                artifact.manifest_digest,
                list(artifact.scope_refs),
                list(artifact.allowed_purposes),
                artifact.byte_count,
                Jsonb(record),
                artifact.created_at,
            ),
        )

    async def append_certification(
        self,
        receipt: OperationalHistoryCertificationReceipt,
    ) -> bool:
        record = certification_record(receipt)
        return await self._put(
            table="operational_history_certification_receipt",
            id_column="receipt_digest",
            identifier=receipt.digest,
            record=record,
            query=(
                "INSERT INTO operational_history_certification_receipt "
                "(receipt_digest, source_revision, complete, scenario_results, "
                "record, recorded_at) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (receipt_digest) DO NOTHING RETURNING receipt_digest"
            ),
            values=(
                receipt.digest,
                receipt.source_revision,
                receipt.operationally_validated,
                Jsonb(record["scenario_results"]),
                Jsonb(record),
                receipt.recorded_at,
            ),
        )

    async def write_storage_pressure(
        self,
        assessment: StoragePressureAssessment,
        *,
        observed_at: datetime,
    ) -> None:
        """Write the current bounded degradation posture for graph admission."""

        value = {
            "schema_version": "1.0.0",
            "level": assessment.level.value,
            "archive_priority": assessment.archive_priority,
            "reduce_nonessential_collection": (assessment.reduce_nonessential_collection),
            "apply_source_admission_budget": assessment.apply_source_admission_budget,
            "hold_completeness_dependent_work": (assessment.hold_completeness_dependent_work),
            "projected_exhaustion_seconds": assessment.projected_exhaustion_seconds,
            "observed_at": observed_at.isoformat(),
        }
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "INSERT INTO state_kv (key, value, updated_at) "
                    "VALUES ('operational-history:storage-pressure', %s, NOW()) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
                    (Jsonb(value),),
                )

    async def get_archive_artifact(
        self,
        manifest_digest: str,
    ) -> OperationalArchiveArtifact | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT record FROM operational_archive_artifact "
                "WHERE manifest_digest=%s ORDER BY created_at DESC LIMIT 1",
                (manifest_digest,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        record = _mapping(row["record"])
        return OperationalArchiveArtifact(
            artifact_digest=_text(record, "artifact_digest"),
            storage_ref=_text(record, "storage_ref"),
            manifest_digest=_text(record, "manifest_digest"),
            scope_refs=_tuple(record, "scope_refs"),
            allowed_purposes=_tuple(record, "allowed_purposes"),
            byte_count=_integer(record, "byte_count"),
            created_at=_timestamp(record, "created_at"),
            digest=_text(record, "digest"),
        )

    async def is_archive_verified(self, manifest_digest: str) -> bool:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT EXISTS (SELECT 1 FROM operational_archive_verification_receipt "
                "WHERE manifest_digest=%s AND verified) AS verified",
                (manifest_digest,),
            )
            row = await cursor.fetchone()
        return row is not None and row["verified"] is True

    async def purge(self, partition_ids: tuple[str, ...]) -> None:
        """Invoke the database-owned exact partition purge gate."""

        if not partition_ids or len(partition_ids) > 256:
            raise ValueError("operational history purge partition set is outside its bound")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                for partition_id in sorted(set(partition_ids)):
                    cursor = await connection.execute(
                        "SELECT fdai_purge_observation_partition(%s) AS deleted_rows",
                        (partition_id,),
                    )
                    row = await cursor.fetchone()
                    if row is None or int(row["deleted_rows"]) < 0:
                        raise RuntimeError("operational history purge returned invalid evidence")

    async def _put(
        self,
        *,
        table: str,
        id_column: str,
        identifier: str,
        record: dict[str, object],
        query: str,
        values: tuple[object, ...],
    ) -> bool:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(query, values)
                created = await cursor.fetchone()
                if created is not None:
                    return True
                retained_cursor = await connection.execute(
                    f"SELECT record FROM {table} WHERE {id_column}=%s",
                    (identifier,),
                )
                retained = await retained_cursor.fetchone()
                if retained is None or _mapping(retained["record"]) != record:
                    raise ValueError("operational history replay changed retained content")
                return False

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _policy_record(value: ObservationRetentionPolicy) -> dict[str, object]:
    return {
        "policy_id": value.policy_id,
        "fact_family": value.fact_family,
        "purpose": value.purpose,
        "hot_retention_seconds": value.hot_retention_seconds,
        "warm_retention_seconds": value.warm_retention_seconds,
        "archive_class": value.archive_class,
        "deletion_method": value.deletion_method.value,
        "review_at": value.review_at.isoformat(),
        "digest": value.digest,
    }


def _incarnation_record(value: ResourceIncarnation) -> dict[str, object]:
    return {
        "incarnation_id": value.incarnation_id,
        "resource_ref": value.resource_ref,
        "resource_type": value.resource_type,
        "provider_identity": value.provider_identity,
        "lifecycle_boundary_ref": value.lifecycle_boundary_ref,
        "opened_at": value.opened_at.isoformat(),
        "closed_at": value.closed_at.isoformat() if value.closed_at else None,
        "opening_observation_id": value.opening_observation_id,
        "closing_observation_id": value.closing_observation_id,
        "digest": value.digest,
    }


def _partition_record(value: ObservationPartition) -> dict[str, object]:
    return {
        "partition_id": value.partition_id,
        "scope_ref": value.scope_ref,
        "interval_start": value.interval_start.isoformat(),
        "interval_end": value.interval_end.isoformat(),
        "first_watermark": value.first_watermark,
        "last_watermark": value.last_watermark,
        "partition_kind": value.kind.value,
        "state": value.state.value,
        "correction_of": value.correction_of,
        "retention_policy_digest": value.retention_policy_digest,
        "created_at": value.created_at.isoformat(),
        "digest": value.digest,
    }


def _checkpoint_record(value: ObservationCheckpoint) -> dict[str, object]:
    return {
        name: (item.isoformat() if isinstance(item := getattr(value, name), datetime) else item)
        for name in ObservationCheckpoint.__dataclass_fields__
    }


def _pin_record(value: ObservationPartitionPin) -> dict[str, object]:
    return {
        "pin_event_id": value.pin_event_id,
        "pin_id": value.pin_id,
        "partition_id": value.partition_id,
        "pin_kind": value.kind.value,
        "case_ref": value.case_ref,
        "placed_at": value.placed_at.isoformat(),
        "released_at": value.released_at.isoformat() if value.released_at else None,
        "expires_at": value.expires_at.isoformat() if value.expires_at else None,
        "evidence_refs": list(value.evidence_refs),
        "digest": value.digest,
    }


def _correction_record(value: ObservationCorrectionReceipt) -> dict[str, object]:
    return {
        "receipt_id": value.receipt_id,
        "correction_partition_id": value.correction_partition_id,
        "affected_checkpoint_ids": list(value.affected_checkpoint_ids),
        "correction_manifest_digest": value.correction_manifest_digest,
        "replay_receipt_digest": value.replay_receipt_digest,
        "resulting_graph_digest": value.resulting_graph_digest,
        "projection_watermark": value.projection_watermark,
        "closed_at": value.closed_at.isoformat(),
        "complete": value.complete,
        "digest": value.digest,
    }


def _artifact_record(value: OperationalArchiveArtifact) -> dict[str, object]:
    return {
        "artifact_digest": value.artifact_digest,
        "storage_ref": value.storage_ref,
        "manifest_digest": value.manifest_digest,
        "scope_refs": list(value.scope_refs),
        "allowed_purposes": list(value.allowed_purposes),
        "byte_count": value.byte_count,
        "created_at": value.created_at.isoformat(),
        "digest": value.digest,
    }


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("operational history record MUST be an object")
    return value


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"operational history {key} MUST be text")
    return item


def _tuple(value: dict[str, object], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, list) or any(not isinstance(entry, str) for entry in item):
        raise ValueError(f"operational history {key} MUST be a string array")
    return tuple(item)


def _integer(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"operational history {key} MUST be an integer")
    return item


def _timestamp(value: dict[str, object], key: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, key).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"operational history {key} MUST be timezone-aware")
    return parsed


__all__ = [
    "PostgresOperationalHistoryConfig",
    "PostgresOperationalHistoryStore",
]
