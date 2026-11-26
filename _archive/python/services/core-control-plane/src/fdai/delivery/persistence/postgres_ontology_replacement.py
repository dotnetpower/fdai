"""Bounded batched writes inside the ontology owner's existing transaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres_ontology_graph import _load_objects
from fdai.delivery.persistence.postgres_ontology_records import _require_type_ref
from fdai.shared.contracts.models import LinkCardinality, OntologyLinkType, OntologyRelease
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    canonical_json_mapping,
    validate_link_record,
)

_BATCH_SIZE = 1000


async def update_existing_object(
    connection: psycopg.AsyncConnection[Any],
    *,
    record: OntologyObjectRecord,
    existing: Mapping[str, Any],
    expected_revision: int | None,
) -> int:
    current_type = str(existing["object_type"])
    current_revision = int(existing["revision"])
    if current_type != record.object_type:
        raise OntologyInstanceValidationError(
            f"ontology object {record.id!r} cannot change type "
            f"from {current_type} to {record.object_type}"
        )
    if expected_revision is not None and expected_revision != current_revision:
        raise OntologyInstanceValidationError(
            f"ontology object {record.id!r} revision mismatch: "
            f"expected {expected_revision}, current {current_revision}"
        )
    revision = current_revision + 1
    await connection.execute(
        "UPDATE ontology_resource SET properties=%s::jsonb, revision=%s, type_version=%s, "
        "catalog_digest=%s, updated_at=NOW() WHERE id=%s",
        (
            canonical_json_mapping(record.properties, path=f"{record.object_type}.properties")[1],
            revision,
            _require_type_ref(record.type_ref).version,
            _require_type_ref(record.type_ref).catalog_digest,
            record.id,
        ),
    )
    return revision


async def replace_records(
    connection: psycopg.AsyncConnection[Any],
    *,
    objects: Sequence[OntologyObjectRecord],
    links: Sequence[OntologyLinkRecord],
    previous_object_ids: Sequence[str],
    previous_link_keys: Sequence[tuple[str, str, str]],
    releases: Mapping[str, OntologyRelease],
    link_types: Mapping[str, OntologyLinkType],
) -> dict[str, int]:
    """Retain CAS, foreign-link protection, and cardinality under caller-owned locks."""
    desired = {record.id: record for record in objects}
    removed = sorted(set(previous_object_ids) - desired.keys())
    identifiers = sorted(set(desired) | set(removed))
    existing: dict[str, Mapping[str, Any]] = {}
    for offset in range(0, len(identifiers), _BATCH_SIZE):
        cursor = await connection.execute(
            "SELECT id, object_type, properties, revision, type_version, catalog_digest "
            "FROM ontology_resource WHERE id=ANY(%s::text[]) ORDER BY id FOR UPDATE",
            (identifiers[offset : offset + _BATCH_SIZE],),
        )
        existing.update((str(row["id"]), row) for row in await cursor.fetchall())
    rows: list[tuple[Any, ...]] = []
    committed_revisions: dict[str, int] = {}
    for record in objects:
        prior = existing.get(record.id)
        revision = int(prior["revision"]) if prior is not None else 0
        if record.revision != revision:
            raise OntologyInstanceValidationError("ontology replacement revision fence mismatch")
        if prior is not None and prior["object_type"] != record.object_type:
            raise OntologyInstanceValidationError("ontology replacement cannot change object type")
        reference = _require_type_ref(record.type_ref)
        if prior is not None and (
            prior["properties"] == record.properties
            and prior["type_version"] == reference.version
            and prior["catalog_digest"] == reference.catalog_digest
        ):
            committed_revisions[record.id] = revision
            continue
        committed_revisions[record.id] = revision + 1
        rows.append(
            (
                record.id,
                record.object_type,
                canonical_json_mapping(record.properties, path="replacement.properties")[1],
                revision + 1,
                reference.version,
                reference.catalog_digest,
            )
        )
    await _write_batches(
        connection,
        "INSERT INTO ontology_resource "
        "(id, object_type, properties, revision, type_version, catalog_digest) "
        "VALUES (%s, %s, %s::jsonb, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
        "properties=EXCLUDED.properties, revision=EXCLUDED.revision, "
        "type_version=EXCLUDED.type_version, catalog_digest=EXCLUDED.catalog_digest, "
        "updated_at=NOW() WHERE ontology_resource.revision=EXCLUDED.revision-1",
        rows,
        require_all=True,
    )
    desired_links = {(record.from_id, record.link_type, record.to_id) for record in links}
    stale_links = sorted(set(previous_link_keys) - desired_links)
    await _write_batches(
        connection,
        "DELETE FROM ontology_link WHERE from_id=%s AND link_type=%s AND to_id=%s",
        stale_links,
    )
    if removed:
        cursor = await connection.execute(
            "SELECT 1 FROM ontology_link WHERE from_id=ANY(%s::text[]) "
            "OR to_id=ANY(%s::text[]) LIMIT 1",
            (removed, removed),
        )
        if await cursor.fetchone() is not None:
            raise OntologyInstanceValidationError(
                "ontology replacement cannot delete objects with foreign relationships"
            )
        await connection.execute(
            "DELETE FROM ontology_resource WHERE id=ANY(%s::text[])", (removed,)
        )
    foreign_ids = sorted(
        {identifier for link in links for identifier in (link.from_id, link.to_id)} - desired.keys()
    )
    endpoint_objects = dict(desired)
    for offset in range(0, len(foreign_ids), _BATCH_SIZE):
        endpoint_objects.update(
            await _load_objects(
                connection,
                identifiers=foreign_ids[offset : offset + _BATCH_SIZE],
                releases=releases,
            )
        )
    await _validate_links(connection, links, endpoint_objects, link_types)
    link_rows = []
    for link_record in links:
        reference = _require_type_ref(link_record.type_ref)
        link_rows.append(
            (
                link_record.link_type,
                link_record.from_id,
                link_record.to_id,
                canonical_json_mapping(link_record.properties, path="replacement.link")[1],
                reference.version,
                reference.catalog_digest,
            )
        )
    await _write_batches(
        connection,
        "INSERT INTO ontology_link "
        "(link_type, from_id, to_id, properties, type_version, catalog_digest) "
        "VALUES (%s, %s, %s, %s::jsonb, %s, %s) ON CONFLICT (from_id, link_type, to_id) "
        "DO UPDATE SET properties=EXCLUDED.properties, type_version=EXCLUDED.type_version, "
        "catalog_digest=EXCLUDED.catalog_digest WHERE "
        "(ontology_link.properties, ontology_link.type_version, ontology_link.catalog_digest) "
        "IS DISTINCT FROM (EXCLUDED.properties, EXCLUDED.type_version, EXCLUDED.catalog_digest)",
        link_rows,
    )
    return committed_revisions


async def _validate_links(
    connection: psycopg.AsyncConnection[Any],
    links: Sequence[OntologyLinkRecord],
    objects: Mapping[str, OntologyObjectRecord],
    link_types: Mapping[str, OntologyLinkType],
) -> None:
    grouped: dict[str, list[OntologyLinkRecord]] = {}
    for link in links:
        validate_link_record(link, link_types=link_types, objects=objects)
        grouped.setdefault(link.link_type, []).append(link)
    for name, records in grouped.items():
        cardinality = link_types[name].cardinality
        if cardinality is LinkCardinality.MANY_TO_MANY:
            continue
        constrain_source = cardinality in {LinkCardinality.ONE_TO_ONE, LinkCardinality.MANY_TO_ONE}
        constrain_target = cardinality in {LinkCardinality.ONE_TO_ONE, LinkCardinality.ONE_TO_MANY}
        source_targets: dict[str, str] = {}
        target_sources: dict[str, str] = {}
        cursor = await connection.execute(
            "SELECT from_id, to_id FROM ontology_link WHERE link_type=%s AND "
            "((%s AND from_id=ANY(%s::text[])) OR (%s AND to_id=ANY(%s::text[])))",
            (
                name,
                constrain_source,
                sorted({item.from_id for item in records}),
                constrain_target,
                sorted({item.to_id for item in records}),
            ),
        )
        pairs = [(str(row["from_id"]), str(row["to_id"])) for row in await cursor.fetchall()]
        pairs.extend((item.from_id, item.to_id) for item in records)
        for source, target in pairs:
            if (
                constrain_source and source in source_targets and source_targets[source] != target
            ) or (
                constrain_target and target in target_sources and target_sources[target] != source
            ):
                raise OntologyInstanceValidationError("ontology replacement violates cardinality")
            source_targets[source] = target
            target_sources[target] = source


async def _write_batches(
    connection: psycopg.AsyncConnection[Any],
    query: str,
    rows: Sequence[tuple[Any, ...]],
    *,
    require_all: bool = False,
) -> None:
    for offset in range(0, len(rows), _BATCH_SIZE):
        chunk = rows[offset : offset + _BATCH_SIZE]
        cursor = connection.cursor()
        await cursor.executemany(query, chunk)
        if require_all and cursor.rowcount != len(chunk):
            raise OntologyInstanceValidationError(
                "ontology replacement insert lost its revision fence"
            )
