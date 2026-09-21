"""Copy-on-write graph versions with a compare-and-swap publication fence."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql

from fdai.delivery.persistence.postgres_ontology_transition import _columns, _version_content
from fdai.shared.providers.ontology_instance import OntologyInstanceValidationError


@dataclass(frozen=True, slots=True)
class VersionedGraphWrite:
    base_version: str
    base_epoch: int
    prepared_version: str | None = None


async def begin_versioned_write(
    connection: psycopg.AsyncConnection[Any],
) -> VersionedGraphWrite | None:
    """Use private temporary tables so existing validation sees one complete graph base."""
    cursor = await connection.execute("SELECT to_regclass('ontology_graph_control') AS relation")
    registration = await cursor.fetchone()
    if registration is None:
        raise OntologyInstanceValidationError("ontology graph storage registration is unavailable")
    if registration["relation"] is None:
        return None
    cursor = await connection.execute(
        "SELECT active_version, epoch FROM ontology_graph_control WHERE singleton"
    )
    control = await cursor.fetchone()
    if control is None:
        raise OntologyInstanceValidationError("ontology graph control is unavailable")
    if control["active_version"] is None:
        return None
    version = control["active_version"]
    cursor = await connection.execute(
        "SELECT version_id FROM ontology_graph_version WHERE version_id=%s AND sealed FOR SHARE",
        (version,),
    )
    if await cursor.fetchone() is None:
        raise OntologyInstanceValidationError("ontology graph base version is unavailable")
    async with asyncio.timeout(30):
        for table in ("ontology_resource", "ontology_link"):
            await connection.execute(
                sql.SQL(
                    "CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS "
                    "INCLUDING CONSTRAINTS INCLUDING INDEXES) ON COMMIT DROP"
                ).format(sql.Identifier(table), sql.Identifier(table + "_legacy"))
            )
            columns = sql.SQL(", ").join(map(sql.Identifier, await _columns(connection, table)))
            await connection.execute(
                sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} WHERE snapshot_version=%s").format(
                    sql.Identifier(table), columns, columns, sql.Identifier(table + "_version")
                ),
                (version,),
            )
    return VersionedGraphWrite(version, control["epoch"])


async def finish_versioned_write(
    connection: psycopg.AsyncConnection[Any], write: VersionedGraphWrite | None
) -> None:
    """Seal relational content before the writer lock; changed bases fail without publication."""
    if write is None:
        return
    async with asyncio.timeout(30):
        sealed = (
            write
            if write.prepared_version is not None
            else await seal_versioned_write(connection, write)
        )
        version = sealed.prepared_version
        unchanged = version == write.base_version
        cursor = await connection.execute(
            "SELECT version_id FROM ontology_graph_version "
            "WHERE version_id=%s AND sealed FOR SHARE",
            (version,),
        )
        if await cursor.fetchone() is None:
            raise OntologyInstanceValidationError("prepared ontology version is unavailable")
        if not unchanged:
            await _materialize_identity_changes(connection, str(version))
        await connection.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_001,))
        cursor = await connection.execute(
            "UPDATE ontology_graph_control SET active_version=%s, epoch=epoch+%s "
            "WHERE singleton AND active_version=%s AND epoch=%s RETURNING epoch",
            (version, 0 if unchanged else 1, write.base_version, write.base_epoch),
        )
        if await cursor.fetchone() is None:
            raise OntologyInstanceValidationError("ontology graph base or ownership epoch changed")


async def seal_versioned_write(
    connection: psycopg.AsyncConnection[Any], write: VersionedGraphWrite
) -> VersionedGraphWrite:
    """Persist complete immutable candidate rows without advancing the active graph."""
    async with asyncio.timeout(30):
        content = await _version_content(connection, None)
        cursor = await connection.execute(
            "SELECT content_digest, object_count, link_count FROM ontology_graph_version "
            "WHERE version_id=%s AND sealed",
            (write.base_version,),
        )
        base = await cursor.fetchone()
        unchanged = base is not None and content == (
            base["content_digest"],
            base["object_count"],
            base["link_count"],
        )
        version = write.base_version if unchanged else uuid.uuid4().hex
        if not unchanged:
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_003,))
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM ontology_graph_version"
            )
            capacity = await cursor.fetchone()
            if capacity is None or capacity["count"] >= 16:
                raise OntologyInstanceValidationError("ontology graph version retention is blocked")
            await connection.execute(
                "INSERT INTO ontology_graph_version (version_id) VALUES (%s)", (version,)
            )
            for table in ("ontology_resource", "ontology_link"):
                columns = sql.SQL(", ").join(map(sql.Identifier, await _columns(connection, table)))
                await connection.execute(
                    sql.SQL("INSERT INTO {} (snapshot_version, {}) SELECT %s, {} FROM {}").format(
                        sql.Identifier(table + "_version"), columns, columns, sql.Identifier(table)
                    ),
                    (version,),
                )
            await connection.execute(
                "UPDATE ontology_graph_version SET content_digest=%s, object_count=%s, "
                "link_count=%s, sealed=TRUE WHERE version_id=%s AND NOT sealed",
                (*content, version),
            )
        await connection.execute("DROP TABLE pg_temp.ontology_link, pg_temp.ontology_resource")
        return VersionedGraphWrite(write.base_version, write.base_epoch, version)


async def _materialize_identity_changes(
    connection: psycopg.AsyncConnection[Any], version: str
) -> None:
    """Preserve incoming foreign keys without deleting retained non-graph evidence."""
    await connection.execute(
        "SELECT id FROM ontology_resource_legacy AS original WHERE NOT EXISTS "
        "(SELECT 1 FROM ontology_resource_version AS desired WHERE snapshot_version=%s "
        "AND desired.id=original.id) ORDER BY id FOR UPDATE",
        (version,),
    )
    cursor = await connection.execute(
        "SELECT namespace.nspname, relation.relname, attribute.attname "
        "FROM pg_constraint AS constraint_record "
        "JOIN pg_class AS relation ON relation.oid=constraint_record.conrelid "
        "JOIN pg_namespace AS namespace ON namespace.oid=relation.relnamespace "
        "JOIN pg_attribute AS attribute ON attribute.attrelid=relation.oid "
        "AND attribute.attnum=constraint_record.conkey[1] "
        "WHERE constraint_record.contype='f' "
        "AND constraint_record.confrelid='ontology_resource_legacy'::regclass "
        "AND relation.oid<>'ontology_link_legacy'::regclass"
    )
    for reference in await cursor.fetchall():
        dependent = await connection.execute(
            sql.SQL(
                "SELECT 1 FROM {} AS dependent JOIN ontology_resource_legacy AS original "
                "ON original.id=dependent.{} WHERE NOT EXISTS (SELECT 1 FROM "
                "ontology_resource_version AS desired WHERE desired.snapshot_version=%s "
                "AND desired.id=original.id) LIMIT 1"
            ).format(
                sql.Identifier(reference["nspname"], reference["relname"]),
                sql.Identifier(reference["attname"]),
            ),
            (version,),
        )
        if await dependent.fetchone() is not None:
            raise OntologyInstanceValidationError(
                "ontology deletion has retained foreign references"
            )
    await connection.execute("SELECT set_config('fdai.ontology_materialization','on',true)")
    await connection.execute(
        "DELETE FROM ontology_link_legacy AS original WHERE NOT EXISTS "
        "(SELECT 1 FROM ontology_resource_version AS desired WHERE snapshot_version=%s "
        "AND desired.id=original.from_id) OR NOT EXISTS "
        "(SELECT 1 FROM ontology_resource_version AS desired WHERE snapshot_version=%s "
        "AND desired.id=original.to_id)",
        (version, version),
    )
    await connection.execute(
        "DELETE FROM ontology_resource_legacy AS original WHERE NOT EXISTS "
        "(SELECT 1 FROM ontology_resource_version AS desired WHERE snapshot_version=%s "
        "AND desired.id=original.id)",
        (version,),
    )
    columns = sql.SQL(", ").join(
        map(sql.Identifier, await _columns(connection, "ontology_resource_legacy"))
    )
    await connection.execute(
        sql.SQL(
            "INSERT INTO ontology_resource_legacy ({}) SELECT {} FROM ontology_resource_version "
            "WHERE snapshot_version=%s ON CONFLICT (id) DO NOTHING"
        ).format(columns, columns),
        (version,),
    )
    await connection.execute("SELECT set_config('fdai.ontology_materialization','',true)")
