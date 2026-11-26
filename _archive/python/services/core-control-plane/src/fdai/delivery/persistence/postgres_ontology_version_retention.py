"""Post-commit retention for rebuildable graph versions, never observation or audit history."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import psycopg
from psycopg.rows import dict_row

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres_ontology import PostgresOntologyInstanceStoreConfig

_LOGGER = logging.getLogger(__name__)


async def prune_graph_versions(config: PostgresOntologyInstanceStoreConfig) -> None:
    """Retain the active graph and seven predecessors; pinned versions may defer cleanup.

    Cleanup has a separate transaction and deadline. Busy cleanup cannot turn an already
    committed publication into a failed write; the publication-time capacity fence remains.
    """
    try:
        async with (
            asyncio.timeout(5),
            await psycopg.AsyncConnection.connect(
                config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
            ) as connection,
        ):
            await connection.execute("SELECT set_config('statement_timeout','3000',true)")
            cursor = await connection.execute(
                "SELECT to_regclass('ontology_graph_control') AS relation"
            )
            registration = await cursor.fetchone()
            if registration is None or registration["relation"] is None:
                return
            cursor = await connection.execute(
                "SELECT active_version FROM ontology_graph_control AS control "
                "JOIN ontology_graph_version AS version "
                "ON version.version_id=control.active_version "
                "WHERE control.singleton AND version.sealed"
            )
            if await cursor.fetchone() is None:
                return
            cursor = await connection.execute(
                "SELECT pg_try_advisory_xact_lock(%s) AS acquired", (8_419_450_002,)
            )
            lock = await cursor.fetchone()
            if lock is None or not lock["acquired"]:
                return
            await connection.execute(
                "DELETE FROM state_kv WHERE starts_with(key,'ontology-version-prepared:') "
                "AND updated_at < clock_timestamp()-INTERVAL '30 minutes'"
            )
            cursor = await connection.execute(
                "SELECT version_id FROM ontology_graph_version AS graph WHERE sealed "
                "AND version_id IS DISTINCT FROM "
                "(SELECT active_version FROM ontology_graph_control WHERE singleton) "
                "AND NOT EXISTS (SELECT 1 FROM state_kv AS preparation "
                "WHERE starts_with(preparation.key,'ontology-version-prepared:') "
                "AND preparation.updated_at>=clock_timestamp()-INTERVAL '30 minutes' "
                "AND (preparation.value->>'version'=graph.version_id "
                "OR preparation.value->>'base_version'=graph.version_id)) "
                "ORDER BY created_at DESC, version_id DESC OFFSET 7 FOR UPDATE SKIP LOCKED"
            )
            for row in await cursor.fetchall():
                version = row["version_id"]
                await connection.execute(
                    "SELECT set_config('fdai.ontology_version_gc',%s,true)", (version,)
                )
                await connection.execute(
                    "DELETE FROM ontology_link_version WHERE snapshot_version=%s", (version,)
                )
                await connection.execute(
                    "DELETE FROM ontology_resource_version WHERE snapshot_version=%s", (version,)
                )
                await connection.execute(
                    "DELETE FROM ontology_graph_version WHERE version_id=%s", (version,)
                )
    except (TimeoutError, psycopg.Error):
        _LOGGER.warning(
            "ontology_version_retention_deferred", extra={"reason": "store_unavailable"}
        )
