"""PostgreSQL implementation of the typed runtime ontology instance graph."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_inventory_observation import (
    advance_ontology_projection,
)
from fdai.delivery.persistence.postgres_ontology_graph import (
    _cardinality_links,
    _load_objects,
    _query_objects,
    _traverse,
)
from fdai.delivery.persistence.postgres_ontology_records import (
    _link_from_row,  # noqa: F401
    _object_from_row,
    _require_projection_revision,
    _require_type_ref,
    _validate_limit,
)
from fdai.delivery.persistence.postgres_ontology_source_coverage import (
    resolve_inventory_graph_source_coverage,
)
from fdai.delivery.persistence.postgres_ontology_source_coverage import (
    resource_graph_source_coverage as _resource_graph_source_coverage,  # noqa: F401
)
from fdai.shared.contracts.models import (
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyDirection,
    OntologyGraphSnapshot,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    canonical_json_mapping,
    normalize_link_record,
    normalize_object_record,
    pin_link_record,
    pin_object_record,
    validate_link_record,
    validate_object_record,
)

_resolve_inventory_graph_source_coverage = resolve_inventory_graph_source_coverage
_SUBGRAPH_REPLACEMENT_LOCK: Final[int] = 8_419_450_001
_INVENTORY_STATE_BATCH_SIZE: Final[int] = 1000


@dataclass(frozen=True, slots=True)
class PostgresOntologyInstanceStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresOntologyInstanceStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")


class PostgresOntologyInstanceStore:
    """Async ontology store backed by ``ontology_resource`` and ``ontology_link``."""

    def __init__(
        self,
        *,
        config: PostgresOntologyInstanceStoreConfig,
        object_types: Sequence[OntologyObjectType],
        link_types: Sequence[OntologyLinkType],
        historical_releases: Sequence[OntologyRelease] = (),
    ) -> None:
        self._config = config
        self._object_types = {item.name: item for item in object_types}
        self._link_types = {item.name: item for item in link_types}
        self._release = build_ontology_release(object_types=object_types, link_types=link_types)
        self._releases = {item.digest: item for item in (*historical_releases, self._release)}

    async def sync_catalog(self) -> None:
        """Persist the exact release and upsert declarations before graph writes."""
        releases = dict(self._releases)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "INSERT INTO ontology_release (digest, manifest) VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (digest) DO NOTHING",
                    (self._release.digest, self._release.model_dump_json()),
                )
                for object_type in self._object_types.values():
                    await connection.execute(
                        "INSERT INTO ontology_object_type "
                        "(name, version, key_field, properties, description) "
                        "VALUES (%s, %s, %s, %s::jsonb, %s) "
                        "ON CONFLICT (name) DO UPDATE SET version = EXCLUDED.version, "
                        "key_field = EXCLUDED.key_field, properties = EXCLUDED.properties, "
                        "description = EXCLUDED.description",
                        (
                            object_type.name,
                            str(object_type.version),
                            object_type.key,
                            json.dumps(
                                {
                                    name: declaration.model_dump(mode="json")
                                    for name, declaration in object_type.properties.items()
                                }
                            ),
                            object_type.description,
                        ),
                    )
                for link_type in self._link_types.values():
                    await connection.execute(
                        "INSERT INTO ontology_link_type "
                        "(name, version, from_type, to_type, cardinality, is_transitive, "
                        "is_causal, temporal_order, order_by_property, description) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (name) DO UPDATE SET version = EXCLUDED.version, "
                        "from_type = EXCLUDED.from_type, to_type = EXCLUDED.to_type, "
                        "cardinality = EXCLUDED.cardinality, "
                        "is_transitive = EXCLUDED.is_transitive, "
                        "is_causal = EXCLUDED.is_causal, "
                        "temporal_order = EXCLUDED.temporal_order, "
                        "order_by_property = EXCLUDED.order_by_property, "
                        "description = EXCLUDED.description",
                        (
                            link_type.name,
                            str(link_type.version),
                            link_type.from_type,
                            link_type.to_type,
                            link_type.cardinality.value,
                            link_type.is_transitive,
                            link_type.is_causal,
                            link_type.temporal_order,
                            link_type.order_by_property,
                            link_type.description,
                        ),
                    )
                cursor = await connection.execute(
                    "SELECT digest, manifest FROM ontology_release ORDER BY digest"
                )
                for row in await cursor.fetchall():
                    release = OntologyRelease.model_validate(row["manifest"])
                    digest = str(row["digest"])
                    if release.digest != digest:
                        raise RuntimeError(
                            f"persisted ontology release manifest does not match digest {digest!r}"
                        )
                    releases[digest] = release
        self._releases = releases

    async def read_inventory_state_base(
        self,
        *,
        object_ids: tuple[str, ...],
        expected_generation: str | None,
    ) -> tuple[OntologyObjectRecord, ...]:
        """Read a manifest-fenced prior Resource generation for transition derivation."""

        if object_ids != tuple(sorted(set(object_ids))) or len(object_ids) > 50_000:
            raise ValueError("inventory state base object ids MUST be unique, ordered, and bounded")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "SELECT key, value FROM state_kv "
                    "WHERE key=ANY(%s::text[]) ORDER BY key FOR SHARE",
                    (
                        [
                            "inventory-ontology:manifest",
                            "inventory-ontology:status",
                        ],
                    ),
                )
                rows = {str(row["key"]): row["value"] for row in await cursor.fetchall()}
                manifest = rows.get("inventory-ontology:manifest")
                status = rows.get("inventory-ontology:status")
                if expected_generation is None:
                    if manifest is not None or (
                        status is not None and not _unavailable_inventory_projection_status(status)
                    ):
                        raise ValueError("inventory ontology state base appeared after enrichment")
                    return ()
                if not isinstance(manifest, dict) or not isinstance(status, dict):
                    raise ValueError("inventory ontology state base is unavailable")
                if not _inventory_state_base_available(
                    manifest,
                    status,
                    expected_generation=expected_generation,
                ):
                    raise ValueError("inventory ontology state base generation is incomplete")
                owned_ids = _inventory_manifest_object_ids(manifest)
                objects: list[OntologyObjectRecord] = []
                for start in range(0, len(object_ids), _INVENTORY_STATE_BATCH_SIZE):
                    selected = tuple(
                        object_id
                        for object_id in object_ids[start : start + _INVENTORY_STATE_BATCH_SIZE]
                        if object_id in owned_ids
                    )
                    if not selected:
                        continue
                    object_cursor = await connection.execute(
                        "SELECT id, object_type, properties, revision, "
                        "type_version, catalog_digest FROM ontology_resource "
                        "WHERE object_type='Resource' AND id=ANY(%s::text[]) "
                        "ORDER BY id",
                        (list(selected),),
                    )
                    objects.extend(
                        _object_from_row(row, releases=self._releases)
                        for row in await object_cursor.fetchall()
                    )
                return tuple(objects)

    async def upsert_object(
        self,
        record: OntologyObjectRecord,
        *,
        expected_revision: int | None = None,
    ) -> OntologyObjectRecord:
        record = normalize_object_record(pin_object_record(record, self._release))
        validate_object_record(record, self._object_types)
        _, properties_json = canonical_json_mapping(
            record.properties,
            path=f"{record.object_type}.properties",
        )
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "SELECT object_type, revision FROM ontology_resource WHERE id = %s FOR UPDATE",
                    (record.id,),
                )
                existing = await cursor.fetchone()
                if existing is None:
                    revision = self._validate_missing_revision(record.id, expected_revision)
                    await connection.execute(
                        "INSERT INTO ontology_resource "
                        "(id, object_type, properties, revision, type_version, catalog_digest) "
                        "VALUES (%s, %s, %s::jsonb, %s, %s, %s)",
                        (
                            record.id,
                            record.object_type,
                            properties_json,
                            revision,
                            _require_type_ref(record.type_ref).version,
                            _require_type_ref(record.type_ref).catalog_digest,
                        ),
                    )
                else:
                    revision = await self._update_existing(
                        connection,
                        record=record,
                        existing=existing,
                        expected_revision=expected_revision,
                    )
        return OntologyObjectRecord(
            id=record.id,
            object_type=record.object_type,
            properties=dict(record.properties),
            revision=revision,
            type_ref=record.type_ref,
        )

    async def create_object_if_absent(
        self,
        record: OntologyObjectRecord,
    ) -> OntologyObjectRecord | None:
        """Atomically insert one object and never overwrite an existing identity."""
        record = normalize_object_record(pin_object_record(record, self._release))
        validate_object_record(record, self._object_types)
        _, properties_json = canonical_json_mapping(
            record.properties,
            path=f"{record.object_type}.properties",
        )
        type_ref = _require_type_ref(record.type_ref)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "INSERT INTO ontology_resource "
                    "(id, object_type, properties, revision, type_version, catalog_digest) "
                    "VALUES (%s, %s, %s::jsonb, 1, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id",
                    (
                        record.id,
                        record.object_type,
                        properties_json,
                        type_ref.version,
                        type_ref.catalog_digest,
                    ),
                )
                if await cursor.fetchone() is None:
                    return None
        return OntologyObjectRecord(
            id=record.id,
            object_type=record.object_type,
            properties=dict(record.properties),
            revision=1,
            type_ref=record.type_ref,
        )

    def _validate_missing_revision(self, object_id: str, expected_revision: int | None) -> int:
        if expected_revision not in (None, 0):
            raise OntologyInstanceValidationError(
                f"ontology object {object_id!r} revision mismatch: "
                f"expected {expected_revision}, current 0"
            )
        return 1

    async def _update_existing(
        self,
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
            "UPDATE ontology_resource "
            "SET properties = %s::jsonb, revision = %s, type_version = %s, "
            "catalog_digest = %s, updated_at = NOW() "
            "WHERE id = %s",
            (
                canonical_json_mapping(
                    record.properties,
                    path=f"{record.object_type}.properties",
                )[1],
                revision,
                _require_type_ref(record.type_ref).version,
                _require_type_ref(record.type_ref).catalog_digest,
                record.id,
            ),
        )
        return revision

    async def upsert_link(self, record: OntologyLinkRecord) -> None:
        record = normalize_link_record(pin_link_record(record, self._release))
        _, properties_json = canonical_json_mapping(
            record.properties,
            path=f"{record.link_type}.properties",
        )
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "SELECT name FROM ontology_link_type WHERE name = %s FOR UPDATE",
                    (record.link_type,),
                )
                objects = await _load_objects(
                    connection,
                    identifiers=(record.from_id, record.to_id),
                    releases=self._releases,
                )
                existing_links = await _cardinality_links(
                    connection,
                    record,
                    releases=self._releases,
                )
                validate_link_record(
                    record,
                    link_types=self._link_types,
                    objects=objects,
                    existing_links=existing_links,
                )
                await connection.execute(
                    "INSERT INTO ontology_link "
                    "(link_type, from_id, to_id, properties, type_version, catalog_digest) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s) "
                    "ON CONFLICT (from_id, link_type, to_id) "
                    "DO UPDATE SET properties = EXCLUDED.properties, "
                    "type_version = EXCLUDED.type_version, "
                    "catalog_digest = EXCLUDED.catalog_digest",
                    (
                        record.link_type,
                        record.from_id,
                        record.to_id,
                        properties_json,
                        _require_type_ref(record.type_ref).version,
                        _require_type_ref(record.type_ref).catalog_digest,
                    ),
                )

    async def replace_subgraph(
        self,
        *,
        objects: Sequence[OntologyObjectRecord],
        links: Sequence[OntologyLinkRecord],
        previous_object_ids: Sequence[str] = (),
        previous_link_keys: Sequence[tuple[str, str, str]] = (),
        _state_updates: Mapping[str, Mapping[str, Any]] | None = None,
        _expected_active_generation: str | None = None,
        _observation_projection_watermark: int | None = None,
    ) -> None:
        normalized_objects = tuple(
            normalize_object_record(pin_object_record(item, self._release)) for item in objects
        )
        normalized_links = tuple(
            normalize_link_record(pin_link_record(item, self._release)) for item in links
        )
        if len({item.id for item in normalized_objects}) != len(normalized_objects):
            raise OntologyInstanceValidationError("replacement object ids MUST be unique")
        if len({(item.from_id, item.link_type, item.to_id) for item in normalized_links}) != len(
            normalized_links
        ):
            raise OntologyInstanceValidationError("replacement link keys MUST be unique")
        for object_record in normalized_objects:
            validate_object_record(object_record, self._object_types)
        desired_ids = {item.id for item in normalized_objects}
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_SUBGRAPH_REPLACEMENT_LOCK,),
                )
                if _expected_active_generation is not None:
                    active_cursor = await connection.execute(
                        "SELECT snapshot_id FROM inventory_active WHERE singleton=TRUE FOR UPDATE"
                    )
                    active = await active_cursor.fetchone()
                    if active is None or str(active["snapshot_id"]) != _expected_active_generation:
                        raise OntologyInstanceValidationError(
                            "inventory ontology generation is no longer active"
                        )
                link_type_names = sorted({record.link_type for record in normalized_links})
                if link_type_names:
                    await connection.execute(
                        "SELECT name FROM ontology_link_type WHERE name = ANY(%s) "
                        "ORDER BY name FOR UPDATE",
                        (link_type_names,),
                    )
                for object_record in normalized_objects:
                    cursor = await connection.execute(
                        "SELECT object_type, revision FROM ontology_resource "
                        "WHERE id = %s FOR UPDATE",
                        (object_record.id,),
                    )
                    existing = await cursor.fetchone()
                    if existing is None:
                        _require_projection_revision(
                            object_id=object_record.id,
                            expected=object_record.revision,
                            current=0,
                        )
                        await connection.execute(
                            "INSERT INTO ontology_resource "
                            "(id, object_type, properties, revision, type_version, catalog_digest) "
                            "VALUES (%s, %s, %s::jsonb, 1, %s, %s)",
                            (
                                object_record.id,
                                object_record.object_type,
                                canonical_json_mapping(
                                    object_record.properties,
                                    path=f"{object_record.object_type}.properties",
                                )[1],
                                _require_type_ref(object_record.type_ref).version,
                                _require_type_ref(object_record.type_ref).catalog_digest,
                            ),
                        )
                    else:
                        _require_projection_revision(
                            object_id=object_record.id,
                            expected=object_record.revision,
                            current=int(existing["revision"]),
                        )
                        await self._update_existing(
                            connection,
                            record=object_record,
                            existing=existing,
                            expected_revision=object_record.revision,
                        )
                for from_id, link_type, to_id in previous_link_keys:
                    await connection.execute(
                        "DELETE FROM ontology_link "
                        "WHERE from_id = %s AND link_type = %s AND to_id = %s",
                        (from_id, link_type, to_id),
                    )
                for object_id in set(previous_object_ids) - desired_ids:
                    await connection.execute(
                        "DELETE FROM ontology_link WHERE from_id = %s OR to_id = %s",
                        (object_id, object_id),
                    )
                    await connection.execute(
                        "DELETE FROM ontology_resource WHERE id = %s",
                        (object_id,),
                    )
                for link_record in normalized_links:
                    link_objects = await _load_objects(
                        connection,
                        identifiers=(link_record.from_id, link_record.to_id),
                        releases=self._releases,
                    )
                    existing_links = await _cardinality_links(
                        connection,
                        link_record,
                        releases=self._releases,
                    )
                    validate_link_record(
                        link_record,
                        link_types=self._link_types,
                        objects=link_objects,
                        existing_links=existing_links,
                    )
                    await connection.execute(
                        "INSERT INTO ontology_link "
                        "(link_type, from_id, to_id, properties, type_version, catalog_digest) "
                        "VALUES (%s, %s, %s, %s::jsonb, %s, %s) "
                        "ON CONFLICT (from_id, link_type, to_id) "
                        "DO UPDATE SET properties = EXCLUDED.properties, "
                        "type_version = EXCLUDED.type_version, "
                        "catalog_digest = EXCLUDED.catalog_digest",
                        (
                            link_record.link_type,
                            link_record.from_id,
                            link_record.to_id,
                            canonical_json_mapping(
                                link_record.properties,
                                path=f"{link_record.link_type}.properties",
                            )[1],
                            _require_type_ref(link_record.type_ref).version,
                            _require_type_ref(link_record.type_ref).catalog_digest,
                        ),
                    )
                for key, value in sorted((_state_updates or {}).items()):
                    await connection.execute(
                        "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
                        (
                            key,
                            canonical_json_mapping(value, path=f"state_updates.{key}")[1],
                        ),
                    )
                if _observation_projection_watermark is not None:
                    if _expected_active_generation is None:
                        raise ValueError(
                            "ontology projection watermark requires an active generation"
                        )
                    await advance_ontology_projection(
                        connection,
                        generation=_expected_active_generation,
                        watermark=_observation_projection_watermark,
                    )

    async def replace_subgraph_with_state(
        self,
        *,
        objects: Sequence[OntologyObjectRecord],
        links: Sequence[OntologyLinkRecord],
        previous_object_ids: Sequence[str],
        previous_link_keys: Sequence[tuple[str, str, str]],
        state_updates: Mapping[str, Mapping[str, Any]],
        expected_active_generation: str,
        observation_projection_watermark: int | None = None,
    ) -> None:
        """Atomically replace a subgraph and advance its state commit markers."""

        await self.replace_subgraph(
            objects=objects,
            links=links,
            previous_object_ids=previous_object_ids,
            previous_link_keys=previous_link_keys,
            _state_updates=state_updates,
            _expected_active_generation=expected_active_generation,
            _observation_projection_watermark=observation_projection_watermark,
        )

    async def write_state_if_active_generation(
        self,
        *,
        expected_active_generation: str,
        state_updates: Mapping[str, Mapping[str, Any]],
    ) -> None:
        """Advance projection status only while its inventory generation is active."""

        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_SUBGRAPH_REPLACEMENT_LOCK,),
                )
                active_cursor = await connection.execute(
                    "SELECT snapshot_id FROM inventory_active WHERE singleton=TRUE FOR UPDATE"
                )
                active = await active_cursor.fetchone()
                if active is None or str(active["snapshot_id"]) != expected_active_generation:
                    raise OntologyInstanceValidationError(
                        "inventory ontology generation is no longer active"
                    )
                for key, value in sorted(state_updates.items()):
                    await connection.execute(
                        "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
                        (
                            key,
                            canonical_json_mapping(value, path=f"state_updates.{key}")[1],
                        ),
                    )

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            objects = await _load_objects(
                connection,
                identifiers=(object_id,),
                releases=self._releases,
            )
        return objects.get(object_id)

    async def delete_object(self, object_id: str) -> bool:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "DELETE FROM ontology_link WHERE from_id = %s OR to_id = %s",
                    (object_id, object_id),
                )
                cursor = await connection.execute(
                    "DELETE FROM ontology_resource WHERE id = %s RETURNING id",
                    (object_id,),
                )
                return await cursor.fetchone() is not None

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        object_ids: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> OntologyGraphSnapshot:
        _validate_limit(limit)
        if (
            len(object_ids) > 1_000
            or len(set(object_ids)) != len(object_ids)
            or any(not object_id or len(object_id) > 1_024 for object_id in object_ids)
        ):
            raise ValueError("object_ids MUST contain at most 1000 unique bounded identities")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            return await _query_objects(
                connection,
                releases=self._releases,
                link_types=self._link_types,
                object_types=object_types,
                object_ids=object_ids,
                property_equals=property_equals,
                limit=limit,
                include_relationships=include_relationships,
            )

    async def traverse(
        self,
        *,
        root_ids: Sequence[str],
        root_object_types: Sequence[str] = (),
        link_types: Sequence[str] = (),
        direction: OntologyDirection = "outgoing",
        max_depth: int = 1,
        limit: int = 500,
    ) -> OntologyGraphSnapshot:
        _validate_limit(limit)
        if not 1 <= max_depth <= 5:
            raise ValueError("max_depth MUST be in [1, 5]")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction MUST be outgoing, incoming, or both")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            return await _traverse(
                connection,
                releases=self._releases,
                declared_link_types=self._link_types,
                root_ids=root_ids,
                root_object_types=root_object_types,
                link_types=link_types,
                direction=direction,
                max_depth=max_depth,
                limit=limit,
            )

    async def traverse_from_type(
        self,
        *,
        root_object_type: str,
        link_types: Sequence[str] = (),
        direction: OntologyDirection = "outgoing",
        max_depth: int = 1,
        limit: int = 500,
    ) -> OntologyGraphSnapshot:
        _validate_limit(limit)
        if not root_object_type.strip():
            raise ValueError("root_object_type MUST be non-empty")
        if not 1 <= max_depth <= 5:
            raise ValueError("max_depth MUST be in [1, 5]")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction MUST be outgoing, incoming, or both")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT id FROM ontology_resource WHERE object_type=%s ORDER BY id LIMIT %s",
                (root_object_type, limit + 1),
            )
            selected = tuple(str(row["id"]) for row in await cursor.fetchall())
            return await _traverse(
                connection,
                releases=self._releases,
                declared_link_types=self._link_types,
                root_ids=selected[:limit],
                root_object_types=(root_object_type,),
                link_types=link_types,
                direction=direction,
                max_depth=max_depth,
                limit=limit,
                initially_truncated=len(selected) > limit,
            )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")


def _inventory_state_base_available(
    manifest: Mapping[str, Any],
    status: Mapping[str, Any],
    *,
    expected_generation: str,
) -> bool:
    if manifest.get("generation") != expected_generation or manifest.get("complete") is not True:
        return False
    return (
        status.get("generation") == expected_generation
        and status.get("status") == "available"
        and status.get("complete") is True
    ) or _unavailable_inventory_projection_status(status)


def _unavailable_inventory_projection_status(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("status") == "unavailable"
        and value.get("complete") is False
    )


def _inventory_manifest_object_ids(manifest: Mapping[str, Any]) -> frozenset[str]:
    content = manifest.get("object_content")
    if not isinstance(content, list):
        raise ValueError("inventory ontology manifest object ownership is unavailable")
    identifiers: list[str] = []
    for item in content:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise ValueError("inventory ontology manifest object ownership is malformed")
        identifiers.append(str(item["id"]))
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("inventory ontology manifest object ownership is duplicated")
    return frozenset(identifiers)


__all__ = ["PostgresOntologyInstanceStore", "PostgresOntologyInstanceStoreConfig"]
