"""Bind normalized observations to incarnations and logical history partitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationPartition,
    ObservationPartitionKind,
    ObservationPartitionState,
    ResourceIncarnation,
    build_correction_receipt,
    build_observation_partition,
    build_resource_incarnation,
)
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)


async def bind_observation_lifecycle(
    connection: psycopg.AsyncConnection[Any],
    observations: Sequence[NormalizedInventoryObservation],
) -> None:
    """Atomically bind each retained observation to exact lifecycle identities."""

    ordered = sorted(
        observations,
        key=lambda item: (
            _binding_priority(item),
            item.effective_at,
            item.observation_id,
        ),
    )
    for observation in ordered:
        watermark = await _watermark(connection, observation.observation_id)
        policy_digest = await _policy_digest(connection, _fact_family(observation))
        late = await _is_late(connection, observation)
        partition = await _partition(
            connection,
            observation,
            watermark=watermark,
            policy_digest=policy_digest,
            late=late,
        )
        incarnation_id: str | None = None
        from_incarnation_id: str | None = None
        to_incarnation_id: str | None = None
        if observation.subject_kind is InventoryObservationSubjectKind.OBJECT:
            incarnation_id = await _object_incarnation(connection, observation)
        else:
            from_incarnation_id = await _current_incarnation(
                connection,
                _required(observation.from_id, "relationship from_id"),
            )
            to_incarnation_id = await _current_incarnation(
                connection,
                _required(observation.to_id, "relationship to_id"),
            )
        cursor = await connection.execute(
            "INSERT INTO inventory_observation_lifecycle_binding "
            "(observation_id, incarnation_id, from_incarnation_id, to_incarnation_id, "
            "partition_id, bound_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (observation_id) DO NOTHING RETURNING observation_id",
            (
                observation.observation_id,
                incarnation_id,
                from_incarnation_id,
                to_incarnation_id,
                partition.partition_id,
                observation.recorded_at,
            ),
        )
        if await cursor.fetchone() is None:
            retained = await connection.execute(
                "SELECT incarnation_id, from_incarnation_id, to_incarnation_id, partition_id "
                "FROM inventory_observation_lifecycle_binding WHERE observation_id=%s",
                (observation.observation_id,),
            )
            row = await retained.fetchone()
            expected = (
                incarnation_id,
                from_incarnation_id,
                to_incarnation_id,
                partition.partition_id,
            )
            if row is None or tuple(row.values()) != expected:
                raise ValueError("observation lifecycle replay changed retained binding")


async def _partition(
    connection: psycopg.AsyncConnection[Any],
    observation: NormalizedInventoryObservation,
    *,
    watermark: int,
    policy_digest: str,
    late: bool,
) -> ObservationPartition:
    scope_ref = observation.scope_ref
    if scope_ref is None:
        raise ValueError("observation lifecycle requires an exact scope_ref")
    interval_start = observation.effective_at.astimezone(UTC).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    kind = ObservationPartitionKind.CORRECTION if late else ObservationPartitionKind.BASE
    correction_of = None
    if late:
        cursor = await connection.execute(
            "SELECT partition_id FROM inventory_observation_partition "
            "WHERE scope_ref=%s AND partition_kind='base' "
            "AND interval_start<=%s AND interval_end>%s "
            "ORDER BY created_at DESC LIMIT 1",
            (scope_ref, observation.effective_at, observation.effective_at),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("late observation has no affected base partition")
        correction_of = str(row["partition_id"])
    partition = build_observation_partition(
        scope_ref=scope_ref,
        interval_start=interval_start,
        interval_end=interval_start + timedelta(days=1),
        first_watermark=watermark,
        last_watermark=watermark,
        kind=kind,
        state=(
            ObservationPartitionState.CORRECTION_PENDING if late else ObservationPartitionState.OPEN
        ),
        correction_of=correction_of,
        retention_policy_digest=policy_digest,
        created_at=observation.recorded_at,
    )
    record = {
        "partition_id": partition.partition_id,
        "scope_ref": partition.scope_ref,
        "interval_start": partition.interval_start.isoformat(),
        "interval_end": partition.interval_end.isoformat(),
        "first_watermark": partition.first_watermark,
        "last_watermark": partition.last_watermark,
        "partition_kind": partition.kind.value,
        "state": partition.state.value,
        "correction_of": partition.correction_of,
        "retention_policy_digest": partition.retention_policy_digest,
        "created_at": partition.created_at.isoformat(),
        "digest": partition.digest,
    }
    inserted = await connection.execute(
        "INSERT INTO inventory_observation_partition "
        "(partition_id, scope_ref, interval_start, interval_end, first_watermark, "
        "last_watermark, partition_kind, state, correction_of, retention_policy_digest, "
        "record, created_at, updated_at) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (partition_id) DO NOTHING RETURNING partition_id",
        (
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
    if await inserted.fetchone() is None:
        retained = await connection.execute(
            "SELECT record FROM inventory_observation_partition WHERE partition_id=%s",
            (partition.partition_id,),
        )
        row = await retained.fetchone()
        if row is None or _mapping(row["record"]) != record:
            raise ValueError("observation partition replay changed retained content")
    return partition


async def _object_incarnation(
    connection: psycopg.AsyncConnection[Any],
    observation: NormalizedInventoryObservation,
) -> str:
    cursor = await connection.execute(
        "SELECT incarnation_id FROM inventory_resource_incarnation "
        "WHERE resource_ref=%s AND closed_at IS NULL FOR UPDATE",
        (observation.subject_ref,),
    )
    row = await cursor.fetchone()
    if row is None:
        prior_cursor = await connection.execute(
            "SELECT incarnation_id, closed_at FROM inventory_resource_incarnation "
            "WHERE resource_ref=%s ORDER BY opened_at DESC LIMIT 1 FOR UPDATE",
            (observation.subject_ref,),
        )
        prior = await prior_cursor.fetchone()
        incarnation_id: str | None
        if (
            prior is not None
            and prior["closed_at"] is not None
            and observation.effective_at <= prior["closed_at"]
        ):
            incarnation_id = str(prior["incarnation_id"])
        else:
            incarnation_id = (
                await _materialize_snapshot_incarnation(
                    connection,
                    resource_ref=observation.subject_ref,
                )
                if prior is None
                else None
            )
        if incarnation_id is None:
            if observation.observation_kind is not InventoryObservationKind.FULL:
                raise ValueError("sparse or tombstone observation has no current incarnation")
            incarnation = build_resource_incarnation(
                resource_ref=observation.subject_ref,
                resource_type=observation.subject_type,
                provider_identity=observation.provider_ref
                or f"{observation.source_identity}:{observation.subject_ref}",
                lifecycle_boundary_ref=observation.source_revision,
                opened_at=observation.effective_at,
                opening_observation_id=observation.observation_id,
            )
            await _insert_incarnation(connection, incarnation)
            incarnation_id = incarnation.incarnation_id
    else:
        incarnation_id = str(row["incarnation_id"])
    if (
        observation.mutation_kind is InventoryMutationKind.DELETE
        and observation.tombstone_confirmed
    ):
        await connection.execute(
            "UPDATE inventory_resource_incarnation SET "
            "closed_at=%s, closing_observation_id=%s, "
            "record=record || jsonb_build_object("
            "'closed_at', %s::text, 'closing_observation_id', %s::text) "
            "WHERE incarnation_id=%s AND closed_at IS NULL",
            (
                observation.effective_at,
                observation.observation_id,
                observation.effective_at.isoformat(),
                observation.observation_id,
                incarnation_id,
            ),
        )
    return incarnation_id


async def _current_incarnation(
    connection: psycopg.AsyncConnection[Any],
    resource_ref: str,
) -> str:
    cursor = await connection.execute(
        "SELECT incarnation_id FROM inventory_resource_incarnation "
        "WHERE resource_ref=%s AND closed_at IS NULL",
        (resource_ref,),
    )
    row = await cursor.fetchone()
    if row is None:
        prior_cursor = await connection.execute(
            "SELECT 1 FROM inventory_resource_incarnation WHERE resource_ref=%s LIMIT 1",
            (resource_ref,),
        )
        if await prior_cursor.fetchone() is not None:
            raise ValueError("relationship observation endpoint has no current incarnation")
        incarnation_id = await _materialize_snapshot_incarnation(
            connection,
            resource_ref=resource_ref,
        )
        if incarnation_id is None:
            raise ValueError("relationship observation endpoint has no current incarnation")
        return incarnation_id
    return str(row["incarnation_id"])


async def _materialize_snapshot_incarnation(
    connection: psycopg.AsyncConnection[Any],
    *,
    resource_ref: str,
) -> str | None:
    cursor = await connection.execute(
        "SELECT s.id AS snapshot_id, s.started_at, r.resource_type, "
        "r.provider_ref, r.last_seen "
        "FROM inventory_active a "
        "JOIN inventory_snapshot s ON s.id=a.snapshot_id AND s.status='active' "
        "JOIN inventory_snapshot_resource r ON r.snapshot_id=s.id "
        "WHERE a.singleton=TRUE AND r.resource_id=%s",
        (resource_ref,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    snapshot_id = str(row["snapshot_id"])
    opened_at = row["last_seen"] or row["started_at"]
    opening_observation_id = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {
                    "kind": "promoted_snapshot_baseline",
                    "snapshot_id": snapshot_id,
                    "resource_ref": resource_ref,
                    "resource_type": str(row["resource_type"]),
                    "provider_ref": row["provider_ref"],
                    "opened_at": opened_at.astimezone(UTC).isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    incarnation = build_resource_incarnation(
        resource_ref=resource_ref,
        resource_type=str(row["resource_type"]),
        provider_identity=str(row["provider_ref"] or f"inventory-snapshot:{snapshot_id}"),
        lifecycle_boundary_ref=f"inventory-snapshot:{snapshot_id}",
        opened_at=opened_at,
        opening_observation_id=opening_observation_id,
    )
    await _insert_incarnation(connection, incarnation)
    return incarnation.incarnation_id


async def _insert_incarnation(
    connection: psycopg.AsyncConnection[Any],
    incarnation: ResourceIncarnation,
) -> None:
    record = {
        "incarnation_id": incarnation.incarnation_id,
        "resource_ref": incarnation.resource_ref,
        "resource_type": incarnation.resource_type,
        "provider_identity": incarnation.provider_identity,
        "lifecycle_boundary_ref": incarnation.lifecycle_boundary_ref,
        "opened_at": incarnation.opened_at.isoformat(),
        "closed_at": None,
        "opening_observation_id": incarnation.opening_observation_id,
        "closing_observation_id": None,
        "digest": incarnation.digest,
    }
    await connection.execute(
        "INSERT INTO inventory_resource_incarnation "
        "(incarnation_id, resource_ref, resource_type, provider_identity, "
        "lifecycle_boundary_ref, opened_at, opening_observation_id, record) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            incarnation.incarnation_id,
            incarnation.resource_ref,
            incarnation.resource_type,
            incarnation.provider_identity,
            incarnation.lifecycle_boundary_ref,
            incarnation.opened_at,
            incarnation.opening_observation_id,
            Jsonb(record),
        ),
    )


async def _watermark(
    connection: psycopg.AsyncConnection[Any],
    observation_id: str,
) -> int:
    cursor = await connection.execute(
        "SELECT watermark FROM inventory_observation_journal WHERE observation_id=%s",
        (observation_id,),
    )
    row = await cursor.fetchone()
    if row is None or int(row["watermark"]) < 1:
        raise RuntimeError("retained observation watermark is unavailable")
    return int(row["watermark"])


async def _policy_digest(
    connection: psycopg.AsyncConnection[Any],
    fact_family: str,
) -> str:
    cursor = await connection.execute(
        "SELECT policy_digest FROM operational_retention_policy "
        "WHERE fact_family=%s ORDER BY "
        "(purpose='safety-hold-unconfigured') ASC, recorded_at DESC LIMIT 1",
        (fact_family,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ValueError("observation retention policy is unavailable")
    return str(row["policy_digest"])


async def _is_late(
    connection: psycopg.AsyncConnection[Any],
    observation: NormalizedInventoryObservation,
) -> bool:
    cursor = await connection.execute(
        "SELECT MAX(effective_at) AS latest_at FROM inventory_observation_journal "
        "WHERE subject_kind=%s AND subject_ref=%s AND observation_id<>%s",
        (
            observation.subject_kind.value,
            observation.subject_ref,
            observation.observation_id,
        ),
    )
    row = await cursor.fetchone()
    return (
        row is not None
        and row["latest_at"] is not None
        and observation.effective_at < row["latest_at"]
    )


def _fact_family(observation: NormalizedInventoryObservation) -> str:
    if observation.subject_kind is InventoryObservationSubjectKind.RELATIONSHIP:
        return "relationship_observation"
    if observation.observation_kind is InventoryObservationKind.CHANGE_HINT:
        return "change_hint"
    if observation.observation_kind is InventoryObservationKind.PARTIAL:
        return "partial_observation"
    if observation.observation_kind is InventoryObservationKind.TOMBSTONE:
        return "confirmed_tombstone" if observation.tombstone_confirmed else "tombstone_candidate"
    return "full_observation"


def _binding_priority(observation: NormalizedInventoryObservation) -> int:
    if (
        observation.subject_kind is InventoryObservationSubjectKind.OBJECT
        and observation.mutation_kind is InventoryMutationKind.UPSERT
    ):
        return 0
    if observation.subject_kind is InventoryObservationSubjectKind.RELATIONSHIP:
        return 1
    return 2


def _required(value: str | None, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} MUST be supplied")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("observation lifecycle record MUST be an object")
    return value


async def close_observation_corrections(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation: str,
    projection_watermark: int,
    closed_at: datetime,
) -> None:
    """Close correction partitions only after the ontology projection advances."""

    manifest_cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
    )
    manifest_row = await manifest_cursor.fetchone()
    manifest = _mapping(manifest_row["value"]) if manifest_row is not None else {}
    graph_digest = manifest.get("manifest_digest")
    if not isinstance(graph_digest, str) or not graph_digest.startswith("sha256:"):
        raise ValueError("ontology manifest digest is unavailable for correction closure")
    cursor = await connection.execute(
        "SELECT partition_id, correction_of FROM inventory_observation_partition "
        "WHERE partition_kind='correction' AND state='correction_pending' "
        "AND last_watermark<=%s ORDER BY partition_id FOR UPDATE",
        (projection_watermark,),
    )
    for row in await cursor.fetchall():
        partition_id = str(row["partition_id"])
        corrected_partition_id = str(row["correction_of"])
        checkpoint_cursor = await connection.execute(
            "SELECT checkpoint_id FROM inventory_observation_checkpoint "
            "WHERE partition_id=ANY(%s::text[]) AND valid "
            "ORDER BY checkpoint_id",
            ([partition_id, corrected_partition_id],),
        )
        checkpoint_ids = tuple(
            str(item["checkpoint_id"]) for item in await checkpoint_cursor.fetchall()
        )
        correction_manifest_digest = _content_digest(
            {
                "correction_partition_id": partition_id,
                "affected_checkpoint_ids": list(checkpoint_ids),
            }
        )
        replay_receipt_digest = _content_digest(
            {
                "generation": generation,
                "projection_watermark": projection_watermark,
                "graph_digest": graph_digest,
            }
        )
        receipt = build_correction_receipt(
            correction_partition_id=partition_id,
            affected_checkpoint_ids=checkpoint_ids,
            correction_manifest_digest=correction_manifest_digest,
            replay_receipt_digest=replay_receipt_digest,
            resulting_graph_digest=graph_digest,
            projection_watermark=projection_watermark,
            closed_at=closed_at,
        )
        record = {
            "receipt_id": receipt.receipt_id,
            "correction_partition_id": receipt.correction_partition_id,
            "affected_checkpoint_ids": list(receipt.affected_checkpoint_ids),
            "correction_manifest_digest": receipt.correction_manifest_digest,
            "replay_receipt_digest": receipt.replay_receipt_digest,
            "resulting_graph_digest": receipt.resulting_graph_digest,
            "projection_watermark": receipt.projection_watermark,
            "closed_at": receipt.closed_at.isoformat(),
            "complete": receipt.complete,
            "digest": receipt.digest,
        }
        await connection.execute(
            "INSERT INTO inventory_observation_correction_receipt "
            "(receipt_id, correction_partition_id, projection_watermark, complete, "
            "record, closed_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (receipt_id) DO NOTHING",
            (
                receipt.receipt_id,
                receipt.correction_partition_id,
                receipt.projection_watermark,
                receipt.complete,
                Jsonb(record),
                receipt.closed_at,
            ),
        )
        await connection.execute(
            "UPDATE inventory_observation_partition "
            "SET state='checkpointed', updated_at=%s WHERE partition_id=%s "
            "AND state='correction_pending'",
            (closed_at, partition_id),
        )


def _content_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["bind_observation_lifecycle", "close_observation_corrections"]
