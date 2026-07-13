"""PostgreSQL implementation of the typed runtime ontology instance graph."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import (
    OntologyDirection,
    OntologyGraphSnapshot,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    validate_link_record,
    validate_object_record,
)

_MAX_LIMIT: Final[int] = 1000


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
    ) -> None:
        self._config = config
        self._object_types = {item.name: item for item in object_types}
        self._link_types = {item.name: item for item in link_types}

    async def upsert_object(
        self,
        record: OntologyObjectRecord,
        *,
        expected_revision: int | None = None,
    ) -> OntologyObjectRecord:
        validate_object_record(record, self._object_types)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "SELECT object_type, revision FROM ontology_resource "
                    "WHERE id = %s FOR UPDATE",
                    (record.id,),
                )
                existing = await cursor.fetchone()
                if existing is None:
                    revision = self._validate_missing_revision(record.id, expected_revision)
                    await connection.execute(
                        "INSERT INTO ontology_resource "
                        "(id, object_type, properties, revision) "
                        "VALUES (%s, %s, %s::jsonb, %s)",
                        (
                            record.id,
                            record.object_type,
                            json.dumps(dict(record.properties), default=str),
                            revision,
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
            "SET properties = %s::jsonb, revision = %s, updated_at = NOW() "
            "WHERE id = %s",
            (json.dumps(dict(record.properties), default=str), revision, record.id),
        )
        return revision

    async def upsert_link(self, record: OntologyLinkRecord) -> None:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                objects = await self._load_objects(
                    connection, identifiers=(record.from_id, record.to_id)
                )
                validate_link_record(record, link_types=self._link_types, objects=objects)
                await connection.execute(
                    "INSERT INTO ontology_link "
                    "(link_type, from_id, to_id, properties) "
                    "VALUES (%s, %s, %s, %s::jsonb) "
                    "ON CONFLICT (from_id, link_type, to_id) "
                    "DO UPDATE SET properties = EXCLUDED.properties",
                    (
                        record.link_type,
                        record.from_id,
                        record.to_id,
                        json.dumps(dict(record.properties), default=str),
                    ),
                )

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            objects = await self._load_objects(connection, identifiers=(object_id,))
        return objects.get(object_id)

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
            params.append(json.dumps(dict(property_equals), default=str))
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
                    "SELECT id, object_type, properties, revision "
                    "FROM ontology_resource {} ORDER BY id LIMIT %s"
                ).format(where),
                tuple(params),
            )
            rows = await cursor.fetchall()
            truncated = len(rows) > limit
            objects = tuple(_object_from_row(row) for row in rows[:limit])
            links = await self._links_within(connection, tuple(item.id for item in objects))
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
            visited = set(roots)
            frontier = set(roots)
            selected_links: dict[tuple[str, str, str], OntologyLinkRecord] = {}
            truncated = False
            for _ in range(max_depth):
                if not frontier:
                    break
                edges = await self._adjacent_links(
                    connection,
                    frontier=frontier,
                    link_types=link_types,
                    direction=direction,
                    limit=limit + 1,
                )
                next_frontier = _unvisited_endpoints(edges, visited)
                for edge in edges:
                    selected_links[(edge.from_id, edge.link_type, edge.to_id)] = edge
                room = limit - len(visited)
                if len(next_frontier) > room:
                    next_frontier = set(sorted(next_frontier)[:room])
                    truncated = True
                visited.update(next_frontier)
                frontier = next_frontier
                if len(edges) > limit or len(visited) >= limit:
                    truncated = True
                    break
            objects_by_id = await self._load_objects(
                connection, identifiers=tuple(sorted(visited))
            )
        links = tuple(
            edge
            for _, edge in sorted(selected_links.items())
            if edge.from_id in objects_by_id and edge.to_id in objects_by_id
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
            "SELECT id, object_type, properties, revision "
            "FROM ontology_resource WHERE id = ANY(%s::text[]) ORDER BY id",
            (list(identifiers),),
        )
        return {str(row["id"]): _object_from_row(row) for row in await cursor.fetchall()}

    async def _links_within(
        self,
        connection: psycopg.AsyncConnection[Any],
        identifiers: Sequence[str],
    ) -> tuple[OntologyLinkRecord, ...]:
        if not identifiers:
            return ()
        cursor = await connection.execute(
            "SELECT link_type, from_id, to_id, properties FROM ontology_link "
            "WHERE from_id = ANY(%s::text[]) AND to_id = ANY(%s::text[]) "
            "ORDER BY from_id, link_type, to_id",
            (list(identifiers), list(identifiers)),
        )
        return tuple(_link_from_row(row) for row in await cursor.fetchall())

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
                "SELECT link_type, from_id, to_id, properties FROM ontology_link "
                "WHERE {}{} ORDER BY from_id, link_type, to_id LIMIT %s"
            ).format(direction_clause, type_clause),
            tuple(params),
        )
        return tuple(_link_from_row(row) for row in await cursor.fetchall())


def _unvisited_endpoints(
    edges: Sequence[OntologyLinkRecord], visited: set[str]
) -> set[str]:
    return {
        identifier
        for edge in edges
        for identifier in (edge.from_id, edge.to_id)
        if identifier not in visited
    }


def _object_from_row(row: Mapping[str, Any]) -> OntologyObjectRecord:
    properties = row["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)
    if not isinstance(properties, Mapping):
        raise RuntimeError("ontology_resource.properties MUST be a JSON object")
    return OntologyObjectRecord(
        id=str(row["id"]),
        object_type=str(row["object_type"]),
        properties=dict(properties),
        revision=int(row["revision"]),
    )


def _link_from_row(row: Mapping[str, Any]) -> OntologyLinkRecord:
    properties = row["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)
    if not isinstance(properties, Mapping):
        raise RuntimeError("ontology_link.properties MUST be a JSON object")
    return OntologyLinkRecord(
        link_type=str(row["link_type"]),
        from_id=str(row["from_id"]),
        to_id=str(row["to_id"]),
        properties=dict(properties),
    )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit MUST be in [1, {_MAX_LIMIT}]")


__all__ = ["PostgresOntologyInstanceStore", "PostgresOntologyInstanceStoreConfig"]
