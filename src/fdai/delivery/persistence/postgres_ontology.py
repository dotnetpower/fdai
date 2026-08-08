"""PostgreSQL implementation of the typed runtime ontology instance graph."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
    OntologyTypeRef,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyDirection,
    OntologyGraphSnapshot,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    can_repeat_link,
    canonical_json_mapping,
    normalize_json_value,
    normalize_link_record,
    normalize_object_record,
    ontology_link_sort_key,
    pin_link_record,
    pin_object_record,
    validate_link_record,
    validate_object_record,
)

_MAX_LIMIT: Final[int] = 1000
_SUBGRAPH_REPLACEMENT_LOCK: Final[int] = 8_419_450_001


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
        """Upsert Git-owned type declarations before writing graph instances."""
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
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
                objects = await self._load_objects(
                    connection, identifiers=(record.from_id, record.to_id)
                )
                existing_links = await self._cardinality_links(connection, record)
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
                    link_objects = await self._load_objects(
                        connection,
                        identifiers=(link_record.from_id, link_record.to_id),
                    )
                    existing_links = await self._cardinality_links(connection, link_record)
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

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            objects = await self._load_objects(connection, identifiers=(object_id,))
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
        property_equals: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> OntologyGraphSnapshot:
        _validate_limit(limit)
        clauses: list[str] = []
        params: list[Any] = []
        if object_types:
            clauses.append("object_type = ANY(%s::text[])")
            params.append(list(object_types))
        if property_equals:
            clauses.append("properties @> %s::jsonb")
            normalized = normalize_json_value(property_equals, path="property_equals")
            params.append(canonical_json_mapping(normalized, path="property_equals")[1])
        where: sql.Composable
        if clauses:
            where = sql.SQL("WHERE ") + sql.SQL(" AND ").join(map(sql.SQL, clauses))
        else:
            where = sql.SQL("")
        params.append(limit + 1)
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                sql.SQL(
                    "SELECT id, object_type, properties, revision, type_version, catalog_digest "
                    "FROM ontology_resource {} ORDER BY id LIMIT %s"
                ).format(where),
                tuple(params),
            )
            rows = await cursor.fetchall()
            truncated = len(rows) > limit
            objects = tuple(_object_from_row(row, releases=self._releases) for row in rows[:limit])
            objects_by_id = {item.id: item for item in objects}
            raw_links = await self._links_within(connection, tuple(objects_by_id))
            links = tuple(
                sorted(
                    raw_links,
                    key=lambda link: ontology_link_sort_key(
                        link,
                        link_types=self._link_types,
                        objects=objects_by_id,
                    ),
                )
            )
        return OntologyGraphSnapshot(objects=objects, links=links, truncated=truncated)

    async def traverse(
        self,
        *,
        root_ids: Sequence[str],
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
            roots = await self._load_objects(connection, identifiers=tuple(root_ids))
            ordered_root_ids = tuple(
                dict.fromkeys(root_id for root_id in root_ids if root_id in roots)
            )
            allowed_root_ids = ordered_root_ids[:limit]
            visited = set(allowed_root_ids)
            frontier: set[tuple[str, str | None]] = {
                (root_id, None) for root_id in allowed_root_ids
            }
            expanded: set[tuple[str, str | None]] = set()
            selected_links: dict[tuple[str, str, str], OntologyLinkRecord] = {}
            truncated = len(ordered_root_ids) > limit
            for _ in range(max_depth):
                states = frontier - expanded
                if not states:
                    break
                expanded.update(states)
                frontier_ids = {object_id for object_id, _ in states}
                edges = await self._adjacent_links(
                    connection,
                    frontier=frontier_ids,
                    link_types=link_types,
                    direction=direction,
                    limit=limit + 1,
                )
                next_states: set[tuple[str, str]] = set()
                for object_id, previous_link_type in sorted(states):
                    for edge in edges:
                        next_id = _next_endpoint(edge, object_id=object_id, direction=direction)
                        if next_id is None:
                            continue
                        declaration = self._link_types[edge.link_type]
                        if not can_repeat_link(previous_link_type, declaration):
                            continue
                        selected_links[(edge.from_id, edge.link_type, edge.to_id)] = edge
                        next_states.add((next_id, edge.link_type))
                room = limit - len(visited)
                new_ids = sorted({object_id for object_id, _ in next_states} - visited)
                allowed_new_ids = set(new_ids[:room])
                if len(new_ids) > room:
                    truncated = True
                visited.update(allowed_new_ids)
                frontier = {
                    state
                    for state in next_states
                    if state[0] in visited or state[0] in allowed_new_ids
                }
                if len(edges) > limit or truncated:
                    truncated = True
                    break
            objects_by_id = await self._load_objects(connection, identifiers=tuple(sorted(visited)))
        links = tuple(
            sorted(
                (
                    edge
                    for edge in selected_links.values()
                    if edge.from_id in objects_by_id and edge.to_id in objects_by_id
                ),
                key=lambda link: ontology_link_sort_key(
                    link,
                    link_types=self._link_types,
                    objects=objects_by_id,
                ),
            )
        )
        return OntologyGraphSnapshot(
            objects=tuple(objects_by_id[key] for key in sorted(objects_by_id)),
            links=links,
            truncated=truncated,
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

    async def _load_objects(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        identifiers: Sequence[str],
    ) -> dict[str, OntologyObjectRecord]:
        if not identifiers:
            return {}
        cursor = await connection.execute(
            "SELECT id, object_type, properties, revision, type_version, catalog_digest "
            "FROM ontology_resource WHERE id = ANY(%s::text[]) ORDER BY id",
            (list(identifiers),),
        )
        return {
            str(row["id"]): _object_from_row(row, releases=self._releases)
            for row in await cursor.fetchall()
        }

    async def _links_within(
        self,
        connection: psycopg.AsyncConnection[Any],
        identifiers: Sequence[str],
    ) -> tuple[OntologyLinkRecord, ...]:
        if not identifiers:
            return ()
        cursor = await connection.execute(
            "SELECT link_type, from_id, to_id, properties, type_version, catalog_digest "
            "FROM ontology_link "
            "WHERE from_id = ANY(%s::text[]) AND to_id = ANY(%s::text[]) "
            "ORDER BY from_id, link_type, to_id",
            (list(identifiers), list(identifiers)),
        )
        return tuple(
            _link_from_row(row, releases=self._releases) for row in await cursor.fetchall()
        )

    async def _cardinality_links(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: OntologyLinkRecord,
    ) -> tuple[OntologyLinkRecord, ...]:
        cursor = await connection.execute(
            "SELECT link_type, from_id, to_id, properties, type_version, catalog_digest "
            "FROM ontology_link "
            "WHERE link_type = %s AND (from_id = %s OR to_id = %s) "
            "ORDER BY from_id, to_id",
            (record.link_type, record.from_id, record.to_id),
        )
        return tuple(
            _link_from_row(row, releases=self._releases) for row in await cursor.fetchall()
        )

    async def _adjacent_links(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        frontier: set[str],
        link_types: Sequence[str],
        direction: OntologyDirection,
        limit: int,
    ) -> tuple[OntologyLinkRecord, ...]:
        direction_clause = {
            "outgoing": sql.SQL("from_id = ANY(%s::text[])"),
            "incoming": sql.SQL("to_id = ANY(%s::text[])"),
            "both": sql.SQL("(from_id = ANY(%s::text[]) OR to_id = ANY(%s::text[]))"),
        }[direction]
        params: list[Any] = [list(frontier)]
        if direction == "both":
            params.append(list(frontier))
        type_clause = sql.SQL("")
        if link_types:
            type_clause = sql.SQL(" AND link_type = ANY(%s::text[])")
            params.append(list(link_types))
        params.append(limit)
        cursor = await connection.execute(
            sql.SQL(
                "SELECT link_type, from_id, to_id, properties, type_version, catalog_digest "
                "FROM ontology_link "
                "WHERE {}{} ORDER BY from_id, link_type, to_id LIMIT %s"
            ).format(direction_clause, type_clause),
            tuple(params),
        )
        return tuple(
            _link_from_row(row, releases=self._releases) for row in await cursor.fetchall()
        )


def _next_endpoint(
    edge: OntologyLinkRecord,
    *,
    object_id: str,
    direction: OntologyDirection,
) -> str | None:
    if direction in {"outgoing", "both"} and edge.from_id == object_id:
        return edge.to_id
    if direction in {"incoming", "both"} and edge.to_id == object_id:
        return edge.from_id
    return None


def _object_from_row(
    row: Mapping[str, Any],
    *,
    releases: Mapping[str, OntologyRelease] | None = None,
) -> OntologyObjectRecord:
    properties = row["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)
    if not isinstance(properties, Mapping):
        raise RuntimeError("ontology_resource.properties MUST be a JSON object")
    normalized = normalize_json_value(properties, path="ontology_resource.properties")
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping normalizes to dict
        raise RuntimeError("ontology_resource.properties MUST be a JSON object")
    return OntologyObjectRecord(
        id=str(row["id"]),
        object_type=str(row["object_type"]),
        properties=normalized,
        revision=int(row["revision"]),
        type_ref=_row_type_ref(
            row,
            kind=OntologyDeclarationKind.OBJECT,
            name=str(row["object_type"]),
            releases=releases,
        ),
    )


def _link_from_row(
    row: Mapping[str, Any],
    *,
    releases: Mapping[str, OntologyRelease] | None = None,
) -> OntologyLinkRecord:
    properties = row["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)
    if not isinstance(properties, Mapping):
        raise RuntimeError("ontology_link.properties MUST be a JSON object")
    normalized = normalize_json_value(properties, path="ontology_link.properties")
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping normalizes to dict
        raise RuntimeError("ontology_link.properties MUST be a JSON object")
    return OntologyLinkRecord(
        link_type=str(row["link_type"]),
        from_id=str(row["from_id"]),
        to_id=str(row["to_id"]),
        properties=normalized,
        type_ref=_row_type_ref(
            row,
            kind=OntologyDeclarationKind.LINK,
            name=str(row["link_type"]),
            releases=releases,
        ),
    )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit MUST be in [1, {_MAX_LIMIT}]")


def _require_type_ref(value: OntologyTypeRef | None) -> OntologyTypeRef:
    if value is None:
        raise RuntimeError("ontology record MUST be pinned before persistence")
    return value


def _require_projection_revision(*, object_id: str, expected: int, current: int) -> None:
    if expected != current:
        raise OntologyInstanceValidationError(
            f"ontology projection {object_id!r} revision fence mismatch: "
            f"expected {expected}, current {current}"
        )


def _row_type_ref(
    row: Mapping[str, Any],
    *,
    kind: OntologyDeclarationKind,
    name: str,
    releases: Mapping[str, OntologyRelease] | None,
) -> OntologyTypeRef | None:
    version = row.get("type_version")
    digest = row.get("catalog_digest")
    if version is None and digest is None:
        return None
    if not isinstance(version, str) or not isinstance(digest, str):
        raise RuntimeError("persisted ontology type reference is incomplete")
    if releases is None:
        return OntologyTypeRef(kind=kind, name=name, version=version, catalog_digest=digest)
    release = releases.get(digest)
    if release is None:
        raise RuntimeError(f"persisted ontology release {digest!r} is unavailable")
    try:
        reference = release.type_ref(kind, name)
    except KeyError as exc:
        raise RuntimeError(
            f"persisted ontology release {digest!r} has no {kind.value} declaration {name!r}"
        ) from exc
    if reference.version != version:
        raise RuntimeError(
            f"persisted ontology type reference version {version!r} does not match "
            f"release {digest!r}"
        )
    return reference


__all__ = ["PostgresOntologyInstanceStore", "PostgresOntologyInstanceStoreConfig"]
