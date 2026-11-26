"""Persist compact inventory snapshot membership and reconstruct journal observations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import psycopg

from fdai.delivery.inventory_semantic_digest import inventory_subject_semantic_digest
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    _snapshot_key,
    observation_from_row,
)
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    mapping as _mapping,
)
from fdai.delivery.persistence.postgres_inventory_shared_membership import (
    require_membership_namespace,
    store_shared_membership,
)
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
)

MAX_SNAPSHOT_MEMBERS = 250_000
_SELECT_JOURNAL_RECORD = (
    "SELECT to_jsonb(journal) - 'watermark' AS record "
    "FROM inventory_observation_journal AS journal "
    "WHERE journal.subject_kind=member.subject_kind "
    "AND journal.subject_ref=member.subject_ref "
    "AND journal.source_identity='inventory.reconciliation' "
    "AND journal.source_event_id LIKE 'snapshot:%%' "
    "AND journal.observation_kind='full' AND journal.mutation_kind='upsert' "
    "AND journal.watermark<=generation.journal_high_watermark "
    "ORDER BY journal.watermark DESC LIMIT 1"
)


async def store_snapshot_membership(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation_id: str,
    source: str,
    observation_kind: str,
    scopes: Sequence[str],
    resource_types: Sequence[str],
    coverage_scope: str | None,
    semantic_content_digest: str,
    journal_high_watermark: int,
    recorded_at: datetime,
    history_visible: bool,
    links_complete: bool,
    records: Sequence[NormalizedInventoryObservation],
) -> int:
    await require_membership_namespace(connection)
    if len(records) > MAX_SNAPSHOT_MEMBERS:
        raise ValueError("inventory snapshot membership exceeds its bound")
    if any(
        item.observation_kind is not InventoryObservationKind.FULL
        or item.mutation_kind is not InventoryMutationKind.UPSERT
        or not item.properties_complete
        for item in records
    ):
        raise ValueError("inventory snapshot membership accepts full observations only")
    generation_values = (
        source,
        observation_kind,
        _canonical_json(list(scopes)),
        _canonical_json(list(resource_types)),
        coverage_scope,
        semantic_content_digest,
        recorded_at,
        history_visible,
        links_complete,
    )
    existing_cursor = await connection.execute(
        "SELECT source, observation_kind, scopes, resource_types, coverage_scope, "
        "semantic_content_digest, journal_high_watermark, recorded_at, history_visible, "
        "links_complete FROM inventory_observation_snapshot_generation "
        "WHERE generation_id=%s",
        (generation_id,),
    )
    existing = await existing_cursor.fetchone()
    members = tuple(_member_values(generation_id, item) for item in records)
    expected_members = {(str(values[1]), str(values[2])): values[1:] for values in members}
    if len(expected_members) != len(members):
        raise ValueError("inventory snapshot contains duplicate subject membership")
    if existing is not None:
        actual_generation = (
            str(existing["source"]),
            str(existing["observation_kind"]),
            _canonical_json(existing["scopes"]),
            _canonical_json(existing["resource_types"]),
            existing["coverage_scope"],
            str(existing["semantic_content_digest"]),
            existing["recorded_at"],
            bool(existing["history_visible"]),
            bool(existing["links_complete"]),
        )
        if actual_generation != generation_values or int(existing["journal_high_watermark"]) > (
            journal_high_watermark
        ):
            raise ValueError("inventory snapshot membership generation changed")
        member_cursor = await connection.execute(
            "SELECT subject_kind, subject_ref, subject_type, semantic_digest, provider_ref, "
            "scope_ref, observed_at, freshness_properties, from_id, from_type, link_type, "
            "to_id, to_type FROM inventory_observation_snapshot_member "
            "WHERE generation_id=%s ORDER BY subject_kind, subject_ref",
            (generation_id,),
        )
        stored_members = await member_cursor.fetchall()
        actual_members = {
            (str(row["subject_kind"]), str(row["subject_ref"])): _stored_member_key(row)
            for row in stored_members
        }
        if actual_members != expected_members:
            raise ValueError("inventory snapshot membership contents changed")
        return int(existing["journal_high_watermark"])

    await connection.execute(
        "INSERT INTO inventory_observation_snapshot_generation "
        "(generation_id, source, observation_kind, scopes, resource_types, coverage_scope, "
        "semantic_content_digest, journal_high_watermark, recorded_at, history_visible, "
        "links_complete, storage_schema_version) "
        "VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, 2)",
        (
            generation_id,
            source,
            observation_kind,
            _canonical_json(list(scopes)),
            _canonical_json(list(resource_types)),
            coverage_scope,
            semantic_content_digest,
            journal_high_watermark,
            recorded_at,
            history_visible,
            links_complete,
        ),
    )
    await store_shared_membership(
        connection, generation_id=generation_id, members=members, recorded_at=recorded_at
    )
    return journal_high_watermark


async def load_snapshot_generation_records(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation_id: str,
    limit: int,
) -> tuple[NormalizedInventoryObservation, ...] | None:
    """Load bounded full observations for one generation, or None for a legacy generation."""

    await require_membership_namespace(connection)
    generation_cursor = await connection.execute(
        "SELECT generation_id FROM inventory_observation_snapshot_generation "
        "WHERE generation_id=%s",
        (generation_id,),
    )
    if await generation_cursor.fetchone() is None:
        return None
    rows = await _membership_records(
        connection,
        generation_id=generation_id,
        limit=limit,
    )
    return tuple(rows)


async def load_snapshot_history_records(
    connection: psycopg.AsyncConnection[Any],
    *,
    resource_id: str,
    after: datetime,
    limit: int,
) -> tuple[NormalizedInventoryObservation, ...]:
    await require_membership_namespace(connection)
    cursor = await connection.execute(
        psycopg.sql.SQL(
            "WITH history_members AS ("
            "SELECT * FROM inventory_observation_snapshot_member_legacy "
            "WHERE subject_kind='object' AND subject_ref=%s AND observed_at>%s "
            "UNION ALL SELECT member.* "
            "FROM inventory_observation_snapshot_generation generation "
            "CROSS JOIN LATERAL fdai_inventory_shared_snapshot_members("
            "generation.generation_id, 'object', %s) AS item "
            "CROSS JOIN LATERAL jsonb_populate_record("
            "NULL::inventory_observation_snapshot_member_legacy, "
            "item || jsonb_build_object('generation_id', generation.generation_id)) AS member "
            "WHERE generation.storage_schema_version=2 AND generation.history_visible=TRUE) "
            "SELECT generation.generation_id, generation.recorded_at, generation.links_complete, "
            "member.subject_kind, member.subject_ref, member.subject_type, member.semantic_digest, "
            "member.provider_ref, member.scope_ref, member.observed_at, "
            "member.freshness_properties, member.from_id, member.from_type, member.link_type, "
            "member.to_id, member.to_type, latest.record AS journal_record "
            "FROM history_members AS member "
            "JOIN inventory_observation_snapshot_generation AS generation "
            "ON generation.generation_id=member.generation_id "
            "LEFT JOIN LATERAL ({journal}) AS latest ON TRUE "
            "WHERE member.subject_kind='object' AND member.subject_ref=%s "
            "AND member.observed_at>%s AND generation.history_visible=TRUE "
            "ORDER BY member.observed_at, generation.recorded_at, generation.generation_id "
            "LIMIT %s"
        ).format(journal=psycopg.sql.SQL(_SELECT_JOURNAL_RECORD)),
        (resource_id, after, resource_id, resource_id, after, limit + 1),
    )
    rows = await cursor.fetchall()
    if len(rows) > limit:
        raise ValueError("inventory observation replay exceeds its per-resource bound")
    return tuple(_reconstruct_record(row) for row in rows)


async def load_previous_snapshot_members(
    connection: psycopg.AsyncConnection[Any],
    *,
    source: str,
    observation_kind: str,
    scopes: Sequence[str],
    resource_types: Sequence[str],
    coverage_scope: str | None,
) -> tuple[dict[tuple[str, str], dict[str, Any]], bool] | None:
    await require_membership_namespace(connection)
    cursor = await connection.execute(
        "SELECT id, metadata FROM inventory_snapshot WHERE status='superseded' "
        "AND source=%s AND observation_kind=%s AND scopes=%s::jsonb "
        "AND resource_types=%s::jsonb "
        "AND metadata->>'coverage_scope' IS NOT DISTINCT FROM %s "
        "AND metadata->>'projection_complete'='true' "
        "ORDER BY completed_at DESC, id DESC LIMIT 1",
        (
            source,
            observation_kind,
            _canonical_json(list(scopes)),
            _canonical_json(list(resource_types)),
            coverage_scope,
        ),
    )
    previous = await cursor.fetchone()
    if previous is None:
        return None
    generation_id = str(previous["id"])
    metadata = _mapping(previous["metadata"])
    membership_cursor = await connection.execute(
        "SELECT generation_id, links_complete FROM inventory_observation_snapshot_generation "
        "WHERE generation_id=%s",
        (generation_id,),
    )
    membership = await membership_cursor.fetchone()
    if membership is not None:
        member_cursor = await connection.execute(
            "SELECT subject_kind, subject_ref, subject_type, semantic_digest, provider_ref, "
            "scope_ref, from_id, from_type, link_type, to_id, to_type "
            "FROM inventory_observation_snapshot_member WHERE generation_id=%s "
            "ORDER BY subject_kind, subject_ref LIMIT %s",
            (generation_id, MAX_SNAPSHOT_MEMBERS + 1),
        )
        member_rows = await member_cursor.fetchall()
        if len(member_rows) > MAX_SNAPSHOT_MEMBERS:
            raise ValueError("prior inventory snapshot membership exceeds its bound")
        members = {
            (str(row["subject_kind"]), str(row["subject_ref"])): dict(row) for row in member_rows
        }
        return members, bool(membership["links_complete"])

    source_generation = metadata.get("journal_source_generation") or generation_id
    if (
        not isinstance(source_generation, str)
        or not source_generation.strip()
        or len(source_generation) > 256
    ):
        raise ValueError("inventory journal source generation is malformed")
    journal_cursor = await connection.execute(
        "SELECT observation_id, content_digest, idempotency_key, subject_kind, observation_kind, "
        "mutation_kind, subject_ref, subject_type, properties, property_mask, properties_complete, "
        "links_complete, tombstone_confirmed, provider_ref, scope_ref, operation, "
        "operation_status, "
        "source_identity, source_event_id, source_revision, effective_at, observed_at, "
        "evidence_cutoff, recorded_at, ingested_at, provider_event_at, from_id, from_type, "
        "link_type, to_id, to_type FROM inventory_observation_journal "
        "WHERE source_identity='inventory.reconciliation' AND source_revision=%s "
        "AND source_event_id=%s AND observation_kind='full' AND mutation_kind='upsert' "
        "ORDER BY subject_kind, subject_ref LIMIT %s",
        (
            source_generation,
            f"snapshot:{source_generation}",
            MAX_SNAPSHOT_MEMBERS + 1,
        ),
    )
    journal_rows = await journal_cursor.fetchall()
    if len(journal_rows) > MAX_SNAPSHOT_MEMBERS:
        raise ValueError("prior inventory snapshot membership exceeds its bound")
    records = tuple(observation_from_row(row) for row in journal_rows)
    members = {
        (item.subject_kind.value, item.subject_ref): {
            "subject_kind": item.subject_kind.value,
            "subject_ref": item.subject_ref,
            "subject_type": item.subject_type,
            "semantic_digest": inventory_subject_semantic_digest(item),
            "provider_ref": item.provider_ref,
            "scope_ref": item.scope_ref,
            "from_id": item.from_id,
            "from_type": item.from_type,
            "link_type": item.link_type,
            "to_id": item.to_id,
            "to_type": item.to_type,
        }
        for item in records
    }
    return members, bool(records) and all(item.links_complete for item in records)


async def _membership_records(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation_id: str,
    limit: int,
) -> list[NormalizedInventoryObservation]:
    cursor = await connection.execute(
        "SELECT generation.generation_id, generation.recorded_at, generation.links_complete, "
        "member.subject_kind, member.subject_ref, member.subject_type, member.semantic_digest, "
        "member.provider_ref, member.scope_ref, member.observed_at, "
        "member.freshness_properties, member.from_id, member.from_type, member.link_type, "
        "member.to_id, member.to_type, latest.record AS journal_record "
        "FROM inventory_observation_snapshot_generation AS generation "
        "JOIN inventory_observation_snapshot_member AS member "
        "ON member.generation_id=generation.generation_id "
        "LEFT JOIN LATERAL (" + _SELECT_JOURNAL_RECORD + ") AS latest ON TRUE "
        "WHERE generation.generation_id=%s "
        "ORDER BY member.subject_kind, member.subject_ref LIMIT %s",
        (generation_id, limit + 1),
    )
    rows = await cursor.fetchall()
    if len(rows) > limit:
        raise ValueError("active inventory projection replay exceeds its bound")
    return [_reconstruct_record(row) for row in rows]


def _reconstruct_record(row: Mapping[str, Any]) -> NormalizedInventoryObservation:
    raw_record = row.get("journal_record")
    if raw_record is None:
        raise ValueError("inventory snapshot member has no journal source record")
    prior = observation_from_row(_journal_record_mapping(raw_record))
    if (
        prior.observation_kind is not InventoryObservationKind.FULL
        or inventory_subject_semantic_digest(prior) != str(row["semantic_digest"])
    ):
        raise ValueError("inventory snapshot member journal digest changed")
    subject_kind = InventoryObservationSubjectKind(str(row["subject_kind"]))
    properties = dict(prior.properties)
    metadata_property = (
        STATE_FACT_METADATA_PROPERTY
        if subject_kind is InventoryObservationSubjectKind.OBJECT
        else LINK_OBSERVATION_METADATA_PROPERTY
    )
    properties.pop(metadata_property, None)
    properties.update(_mapping(row["freshness_properties"]))
    recorded_at = row["recorded_at"]
    observed_at = row["observed_at"]
    generation_id = str(row["generation_id"])
    subject_ref = str(row["subject_ref"])
    return NormalizedInventoryObservation.create(
        idempotency_key=_snapshot_key(generation_id, subject_kind.value, subject_ref),
        subject_kind=subject_kind,
        observation_kind=InventoryObservationKind.FULL,
        mutation_kind=prior.mutation_kind,
        subject_ref=subject_ref,
        subject_type=str(row["subject_type"]),
        properties=properties,
        property_mask=tuple(properties),
        properties_complete=True,
        links_complete=bool(row["links_complete"]),
        tombstone_confirmed=False,
        provider_ref=(str(row["provider_ref"]) if row["provider_ref"] is not None else None),
        scope_ref=str(row["scope_ref"]) if row["scope_ref"] is not None else None,
        source_identity="inventory.reconciliation",
        source_event_id=f"snapshot:{generation_id}",
        source_revision=generation_id,
        effective_at=observed_at,
        observed_at=observed_at,
        evidence_cutoff=observed_at,
        recorded_at=recorded_at,
        ingested_at=recorded_at,
        from_id=str(row["from_id"]) if row["from_id"] is not None else None,
        from_type=str(row["from_type"]) if row["from_type"] is not None else None,
        link_type=str(row["link_type"]) if row["link_type"] is not None else None,
        to_id=str(row["to_id"]) if row["to_id"] is not None else None,
        to_type=str(row["to_type"]) if row["to_type"] is not None else None,
    )


def _journal_record_mapping(raw_record: object) -> dict[str, Any]:
    """Restore timestamp types from the JSONB representation returned by PostgreSQL."""

    record = dict(_mapping(raw_record))
    for field in (
        "effective_at",
        "observed_at",
        "evidence_cutoff",
        "recorded_at",
        "ingested_at",
        "provider_event_at",
    ):
        value = record.get(field)
        if isinstance(value, str):
            record[field] = datetime.fromisoformat(value)
    return record


def _member_values(
    generation_id: str,
    record: NormalizedInventoryObservation,
) -> tuple[object, ...]:
    properties = record.properties
    metadata_property = (
        STATE_FACT_METADATA_PROPERTY
        if record.subject_kind is InventoryObservationSubjectKind.OBJECT
        else LINK_OBSERVATION_METADATA_PROPERTY
    )
    freshness_properties = (
        {metadata_property: properties[metadata_property]}
        if metadata_property in properties
        else {}
    )
    return (
        generation_id,
        record.subject_kind.value,
        record.subject_ref,
        record.subject_type,
        inventory_subject_semantic_digest(record),
        record.provider_ref,
        record.scope_ref,
        record.observed_at,
        _canonical_json(freshness_properties),
        record.from_id,
        record.from_type,
        record.link_type,
        record.to_id,
        record.to_type,
    )


def _stored_member_key(row: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        str(row["subject_kind"]),
        str(row["subject_ref"]),
        str(row["subject_type"]),
        str(row["semantic_digest"]),
        row["provider_ref"],
        row["scope_ref"],
        row["observed_at"],
        _canonical_json(row["freshness_properties"]),
        row["from_id"],
        row["from_type"],
        row["link_type"],
        row["to_id"],
        row["to_type"],
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
