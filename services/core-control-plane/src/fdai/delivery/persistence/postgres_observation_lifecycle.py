"""Bind normalized observations to incarnations and logical history partitions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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

_OI16_SYNTHETIC_SCOPE = re.compile(r"^synthetic/oi16-certification/[0-9a-f]{48}$")
_OI16_SYNTHETIC_FACT_FAMILY = "oi16_synthetic_full_observation"
_READ_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class _PartitionCandidate:
    observation_id: str
    scope_ref: str
    interval_start: datetime
    interval_end: datetime
    watermark: int
    kind: ObservationPartitionKind
    correction_of: str | None
    retention_policy_digest: str
    created_at: datetime


async def bind_observation_lifecycle(
    connection: psycopg.AsyncConnection[Any],
    observations: Sequence[NormalizedInventoryObservation],
    *,
    allow_oi16_synthetic: bool = False,
) -> frozenset[str]:
    """Atomically bind each retained observation to exact lifecycle identities."""

    replayed: set[str] = set()
    ordered = sorted(
        observations,
        key=lambda item: (
            _binding_priority(item),
            item.effective_at,
            item.observation_id,
        ),
    )
    existing_bindings = await _existing_binding_ids(
        connection,
        tuple(item.observation_id for item in ordered),
    )
    pending = tuple(item for item in ordered if item.observation_id not in existing_bindings)
    replayed.update(existing_bindings)
    if not pending:
        return frozenset(replayed)
    watermarks = await _watermarks(
        connection,
        tuple(item.observation_id for item in pending),
    )
    fact_families = {
        item.observation_id: _fact_family(
            item,
            allow_oi16_synthetic=allow_oi16_synthetic,
        )
        for item in pending
    }
    policy_digests = await _policy_digests(connection, tuple(set(fact_families.values())))
    latest_effective_times = await _latest_effective_times(connection, pending)
    current_incarnations = await _current_incarnations(connection, pending)
    partition_candidates: list[_PartitionCandidate] = []
    incarnation_bindings: dict[str, tuple[str | None, str | None, str | None]] = {}
    for observation in pending:
        watermark = watermarks[observation.observation_id]
        policy_digest = policy_digests[fact_families[observation.observation_id]]
        latest_at = latest_effective_times.get(
            (observation.subject_kind.value, observation.subject_ref)
        )
        late = latest_at is not None and observation.effective_at < latest_at
        partition_candidates.append(
            await _partition_candidate(
                connection,
                observation,
                watermark=watermark,
                policy_digest=policy_digest,
                late=late,
            )
        )
        incarnation_id: str | None = None
        from_incarnation_id: str | None = None
        to_incarnation_id: str | None = None
        if observation.subject_kind is InventoryObservationSubjectKind.OBJECT:
            incarnation_id = current_incarnations.get(observation.subject_ref)
            if incarnation_id is None or observation.mutation_kind is InventoryMutationKind.DELETE:
                incarnation_id = await _object_incarnation(connection, observation)
                if observation.mutation_kind is InventoryMutationKind.DELETE:
                    current_incarnations.pop(observation.subject_ref, None)
                else:
                    current_incarnations[observation.subject_ref] = incarnation_id
        else:
            from_ref = _required(observation.from_id, "relationship from_id")
            to_ref = _required(observation.to_id, "relationship to_id")
            from_incarnation_id = current_incarnations.get(from_ref)
            if from_incarnation_id is None:
                from_incarnation_id = await _current_incarnation(connection, from_ref)
                current_incarnations[from_ref] = from_incarnation_id
            to_incarnation_id = current_incarnations.get(to_ref)
            if to_incarnation_id is None:
                to_incarnation_id = await _current_incarnation(connection, to_ref)
                current_incarnations[to_ref] = to_incarnation_id
        incarnation_bindings[observation.observation_id] = (
            incarnation_id,
            from_incarnation_id,
            to_incarnation_id,
        )
    partitions, partition_ids = _coalesce_partitions(partition_candidates)
    bindings = [
        (
            observation.observation_id,
            *incarnation_bindings[observation.observation_id],
            partition_ids[observation.observation_id],
            observation.recorded_at,
        )
        for observation in pending
    ]
    await _insert_partitions(connection, partitions)
    await _insert_bindings(connection, bindings)
    return frozenset(replayed)


async def _partition_candidate(
    connection: psycopg.AsyncConnection[Any],
    observation: NormalizedInventoryObservation,
    *,
    watermark: int,
    policy_digest: str,
    late: bool,
) -> _PartitionCandidate:
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
    return _PartitionCandidate(
        observation_id=observation.observation_id,
        scope_ref=scope_ref,
        interval_start=interval_start,
        interval_end=interval_start + timedelta(days=1),
        watermark=watermark,
        kind=kind,
        correction_of=correction_of,
        retention_policy_digest=policy_digest,
        created_at=observation.recorded_at,
    )


def _coalesce_partitions(
    candidates: Sequence[_PartitionCandidate],
) -> tuple[tuple[ObservationPartition, ...], dict[str, str]]:
    grouped: dict[
        tuple[
            str,
            datetime,
            datetime,
            ObservationPartitionKind,
            str | None,
            str,
        ],
        list[_PartitionCandidate],
    ] = {}
    for candidate in candidates:
        key = (
            candidate.scope_ref,
            candidate.interval_start,
            candidate.interval_end,
            candidate.kind,
            candidate.correction_of,
            candidate.retention_policy_digest,
        )
        grouped.setdefault(key, []).append(candidate)

    partitions: list[ObservationPartition] = []
    partition_ids: dict[str, str] = {}
    for key, members in grouped.items():
        partition = build_observation_partition(
            scope_ref=key[0],
            interval_start=key[1],
            interval_end=key[2],
            first_watermark=min(item.watermark for item in members),
            last_watermark=max(item.watermark for item in members),
            kind=key[3],
            state=(
                ObservationPartitionState.CORRECTION_PENDING
                if key[3] is ObservationPartitionKind.CORRECTION
                else ObservationPartitionState.OPEN
            ),
            correction_of=key[4],
            retention_policy_digest=key[5],
            created_at=min(item.created_at for item in members),
        )
        partitions.append(partition)
        partition_ids.update(
            {candidate.observation_id: partition.partition_id for candidate in members}
        )
    return tuple(partitions), partition_ids


async def _insert_bindings(
    connection: psycopg.AsyncConnection[Any],
    bindings: Sequence[tuple[str, str | None, str | None, str | None, str, datetime]],
) -> None:
    for offset in range(0, len(bindings), _READ_BATCH_SIZE):
        batch = bindings[offset : offset + _READ_BATCH_SIZE]
        await connection.execute(
            "INSERT INTO inventory_observation_lifecycle_binding "
            "(observation_id, incarnation_id, from_incarnation_id, to_incarnation_id, "
            "partition_id, bound_at) "
            "SELECT item.observation_id, item.incarnation_id, item.from_incarnation_id, "
            "item.to_incarnation_id, item.partition_id, item.bound_at "
            "FROM jsonb_to_recordset(%s::jsonb) AS item("
            "observation_id text, incarnation_id text, from_incarnation_id text, "
            "to_incarnation_id text, partition_id text, bound_at timestamptz) "
            "ON CONFLICT (observation_id) DO NOTHING",
            (
                Jsonb(
                    [
                        {
                            "observation_id": item[0],
                            "incarnation_id": item[1],
                            "from_incarnation_id": item[2],
                            "to_incarnation_id": item[3],
                            "partition_id": item[4],
                            "bound_at": item[5].isoformat(),
                        }
                        for item in batch
                    ]
                ),
            ),
        )
        retained = await connection.execute(
            "SELECT observation_id, incarnation_id, from_incarnation_id, "
            "to_incarnation_id, partition_id "
            "FROM inventory_observation_lifecycle_binding "
            "WHERE observation_id=ANY(%s::text[])",
            ([item[0] for item in batch],),
        )
        retained_by_id = {
            str(row["observation_id"]): (
                row["incarnation_id"],
                row["from_incarnation_id"],
                row["to_incarnation_id"],
                row["partition_id"],
            )
            for row in await retained.fetchall()
        }
        for item in batch:
            if retained_by_id.get(item[0]) != item[1:5]:
                raise ValueError("observation lifecycle replay changed retained binding")


async def _existing_binding_ids(
    connection: psycopg.AsyncConnection[Any],
    observation_ids: Sequence[str],
) -> frozenset[str]:
    existing: set[str] = set()
    for offset in range(0, len(observation_ids), _READ_BATCH_SIZE):
        batch = observation_ids[offset : offset + _READ_BATCH_SIZE]
        cursor = await connection.execute(
            "SELECT observation_id FROM inventory_observation_lifecycle_binding "
            "WHERE observation_id=ANY(%s::text[])",
            (list(batch),),
        )
        existing.update(str(row["observation_id"]) for row in await cursor.fetchall())
    return frozenset(existing)


async def _watermarks(
    connection: psycopg.AsyncConnection[Any],
    observation_ids: Sequence[str],
) -> dict[str, int]:
    watermarks: dict[str, int] = {}
    for offset in range(0, len(observation_ids), _READ_BATCH_SIZE):
        batch = observation_ids[offset : offset + _READ_BATCH_SIZE]
        cursor = await connection.execute(
            "SELECT observation_id, watermark FROM inventory_observation_journal "
            "WHERE observation_id=ANY(%s::text[])",
            (list(batch),),
        )
        for row in await cursor.fetchall():
            watermark = int(row["watermark"])
            if watermark < 1:
                raise RuntimeError("retained observation watermark is unavailable")
            watermarks[str(row["observation_id"])] = watermark
    if len(watermarks) != len(set(observation_ids)):
        raise RuntimeError("retained observation watermark is unavailable")
    return watermarks


async def _policy_digests(
    connection: psycopg.AsyncConnection[Any],
    fact_families: Sequence[str],
) -> dict[str, str]:
    cursor = await connection.execute(
        "SELECT DISTINCT ON (fact_family) fact_family, policy_digest "
        "FROM operational_retention_policy WHERE fact_family=ANY(%s::text[]) "
        "ORDER BY fact_family, (purpose='safety-hold-unconfigured') ASC, "
        "recorded_at DESC",
        (list(fact_families),),
    )
    digests = {
        str(row["fact_family"]): str(row["policy_digest"]) for row in await cursor.fetchall()
    }
    if set(digests) != set(fact_families):
        raise ValueError("observation retention policy is unavailable")
    return digests


async def _latest_effective_times(
    connection: psycopg.AsyncConnection[Any],
    observations: Sequence[NormalizedInventoryObservation],
) -> dict[tuple[str, str], datetime]:
    keys = tuple(sorted({(item.subject_kind.value, item.subject_ref) for item in observations}))
    latest: dict[tuple[str, str], datetime] = {}
    for offset in range(0, len(keys), _READ_BATCH_SIZE):
        batch = keys[offset : offset + _READ_BATCH_SIZE]
        cursor = await connection.execute(
            "SELECT journal.subject_kind, journal.subject_ref, "
            "MAX(journal.effective_at) AS latest_at "
            "FROM inventory_observation_journal AS journal "
            "JOIN unnest(%s::text[], %s::text[]) "
            "AS requested(subject_kind, subject_ref) "
            "ON journal.subject_kind=requested.subject_kind "
            "AND journal.subject_ref=requested.subject_ref "
            "GROUP BY journal.subject_kind, journal.subject_ref",
            ([item[0] for item in batch], [item[1] for item in batch]),
        )
        for row in await cursor.fetchall():
            latest[(str(row["subject_kind"]), str(row["subject_ref"]))] = row["latest_at"]
    return latest


async def _current_incarnations(
    connection: psycopg.AsyncConnection[Any],
    observations: Sequence[NormalizedInventoryObservation],
) -> dict[str, str]:
    resource_refs = tuple(
        sorted(
            {
                ref
                for item in observations
                for ref in (item.subject_ref, item.from_id, item.to_id)
                if ref is not None
            }
        )
    )
    incarnations: dict[str, str] = {}
    for offset in range(0, len(resource_refs), _READ_BATCH_SIZE):
        batch = resource_refs[offset : offset + _READ_BATCH_SIZE]
        cursor = await connection.execute(
            "SELECT resource_ref, incarnation_id FROM inventory_resource_incarnation "
            "WHERE resource_ref=ANY(%s::text[]) AND closed_at IS NULL FOR UPDATE",
            (list(batch),),
        )
        incarnations.update(
            {
                str(row["resource_ref"]): str(row["incarnation_id"])
                for row in await cursor.fetchall()
            }
        )
    return incarnations


def _partition_record(partition: ObservationPartition) -> dict[str, object]:
    return {
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


async def _insert_partitions(
    connection: psycopg.AsyncConnection[Any],
    partitions: Sequence[ObservationPartition],
) -> None:
    for offset in range(0, len(partitions), _READ_BATCH_SIZE):
        batch = partitions[offset : offset + _READ_BATCH_SIZE]
        records = [_partition_record(partition) for partition in batch]
        await connection.execute(
            "INSERT INTO inventory_observation_partition "
            "(partition_id, scope_ref, interval_start, interval_end, first_watermark, "
            "last_watermark, partition_kind, state, correction_of, retention_policy_digest, "
            "record, created_at, updated_at) "
            "SELECT item.partition_id, item.scope_ref, item.interval_start, item.interval_end, "
            "item.first_watermark, item.last_watermark, item.partition_kind, item.state, "
            "item.correction_of, item.retention_policy_digest, item.record, item.created_at, "
            "item.created_at FROM jsonb_to_recordset(%s::jsonb) AS item("
            "partition_id text, scope_ref text, interval_start timestamptz, "
            "interval_end timestamptz, first_watermark bigint, last_watermark bigint, "
            "partition_kind text, state text, correction_of text, "
            "retention_policy_digest text, record jsonb, created_at timestamptz) "
            "ON CONFLICT (partition_id) DO NOTHING",
            (
                Jsonb(
                    [
                        {
                            **record,
                            "record": record,
                            "created_at": partition.created_at.isoformat(),
                        }
                        for partition, record in zip(batch, records, strict=True)
                    ]
                ),
            ),
        )
        retained = await connection.execute(
            "SELECT partition_id, record FROM inventory_observation_partition "
            "WHERE partition_id=ANY(%s::text[])",
            ([partition.partition_id for partition in batch],),
        )
        retained_by_id = {
            str(row["partition_id"]): _mapping(row["record"]) for row in await retained.fetchall()
        }
        for partition, record in zip(batch, records, strict=True):
            if retained_by_id.get(partition.partition_id) != record:
                raise ValueError("observation partition replay changed retained content")


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


def _fact_family(
    observation: NormalizedInventoryObservation,
    *,
    allow_oi16_synthetic: bool = False,
) -> str:
    if observation.subject_kind is InventoryObservationSubjectKind.RELATIONSHIP:
        return "relationship_observation"
    if observation.observation_kind is InventoryObservationKind.CHANGE_HINT:
        return "change_hint"
    if observation.observation_kind is InventoryObservationKind.PARTIAL:
        return "partial_observation"
    if observation.observation_kind is InventoryObservationKind.TOMBSTONE:
        return "confirmed_tombstone" if observation.tombstone_confirmed else "tombstone_candidate"
    if (
        allow_oi16_synthetic
        and observation.scope_ref is not None
        and _OI16_SYNTHETIC_SCOPE.fullmatch(observation.scope_ref) is not None
    ):
        return _OI16_SYNTHETIC_FACT_FAMILY
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
    scope_ref: str | None = None,
) -> None:
    """Close correction partitions only after the ontology projection advances.

    ``scope_ref`` narrows the closure to one exact observation scope. The production
    projection path leaves it unset so every replayed correction closes, while a
    bounded caller can close only the corrections it actually replayed.
    """

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
        "AND last_watermark<=%s AND (%s::text IS NULL OR scope_ref=%s) "
        "ORDER BY partition_id FOR UPDATE",
        (projection_watermark, scope_ref, scope_ref),
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
