"""Ordered projection-state writes inside the graph owner's atomic transaction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    canonical_json_mapping,
)


async def versioned_storage_active(connection: psycopg.AsyncConnection[Any]) -> bool:
    cursor = await connection.execute("SELECT to_regclass('ontology_graph_control') AS relation")
    registration = await cursor.fetchone()
    if registration is None:
        raise OntologyInstanceValidationError("ontology graph storage registration is unavailable")
    if registration["relation"] is None:
        return False
    cursor = await connection.execute(
        "SELECT active_version FROM ontology_graph_control WHERE singleton"
    )
    control = await cursor.fetchone()
    if control is None:
        raise OntologyInstanceValidationError("ontology graph control is unavailable")
    return control["active_version"] is not None


async def write_projection_state(
    connection: psycopg.AsyncConnection[Any], updates: Mapping[str, Mapping[str, Any]]
) -> None:
    for key, value in sorted(updates.items()):
        await connection.execute(
            "INSERT INTO state_kv (key,value) VALUES (%s,%s::jsonb) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()",
            (key, canonical_json_mapping(value, path=f"state_updates.{key}")[1]),
        )


async def lock_projection_state(
    connection: psycopg.AsyncConnection[Any], updates: Mapping[str, Mapping[str, Any]]
) -> None:
    await connection.execute(
        "SELECT key FROM state_kv WHERE key=ANY(%s::text[]) ORDER BY key FOR UPDATE",
        (sorted(updates),),
    )


async def require_active_generation(
    connection: psycopg.AsyncConnection[Any], expected: str
) -> None:
    cursor = await connection.execute(
        "SELECT snapshot_id FROM inventory_active WHERE singleton=TRUE FOR UPDATE"
    )
    active = await cursor.fetchone()
    if active is None or str(active["snapshot_id"]) != expected:
        raise OntologyInstanceValidationError("inventory ontology generation is no longer active")


async def write_fenced_projection_state(
    connection: psycopg.AsyncConnection[Any],
    *,
    expected_generation: str,
    updates: Mapping[str, Mapping[str, Any]],
) -> None:
    versioned = await versioned_storage_active(connection)
    if versioned:
        await write_projection_state(connection, updates)
    await connection.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_001,))
    await require_active_generation(connection, expected_generation)
    if not versioned:
        await write_projection_state(connection, updates)
