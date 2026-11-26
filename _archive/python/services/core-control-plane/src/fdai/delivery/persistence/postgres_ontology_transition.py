"""Explicit transactional versioned graph activation and materialization rollback."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Any

import psycopg
from psycopg import sql

_TABLES = ("ontology_resource", "ontology_link")
_LOCK = 8_419_450_001
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ROWS = 500_000


async def _columns(connection: psycopg.AsyncConnection[Any], table: str) -> list[str]:
    cursor = await connection.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass "
        "AND attnum>0 AND NOT attisdropped ORDER BY attnum",
        (table,),
    )
    return [
        row["attname"] for row in await cursor.fetchall() if row["attname"] != "snapshot_version"
    ]


async def _lock_transition(connection: psycopg.AsyncConnection[Any], *, active: bool) -> None:
    await connection.execute("SELECT set_config('statement_timeout','30000',true)")
    await connection.execute("SELECT set_config('lock_timeout','5000',true)")
    if not active:
        await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
    for table in _TABLES:
        await connection.execute(
            sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                sql.Identifier(table + "_legacy" if active else table)
            )
        )
    if active:
        await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key='ontology:writer-protocol' FOR UPDATE"
    )
    barrier = await cursor.fetchone()
    value = barrier["value"] if barrier is not None else None
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "minimum_writer_version"}
        or value["schema_version"] != "1.0.0"
        or type(value["minimum_writer_version"]) is not int
        or value["minimum_writer_version"] not in (1, 2)
    ):
        raise ValueError("ontology writer barrier is unavailable")
    await connection.execute("SELECT set_config('fdai.ontology_writer_protocol','2',true)")


async def _copy_read_grants(
    connection: psycopg.AsyncConnection[Any], *, original: str, view: str
) -> None:
    defaults = await connection.execute(
        "SELECT DISTINCT privileges.grantee, roles.rolname FROM pg_class AS relation "
        "CROSS JOIN LATERAL aclexplode(COALESCE(relation.relacl, "
        "acldefault('r',relation.relowner))) AS privileges "
        "LEFT JOIN pg_roles AS roles ON roles.oid=privileges.grantee "
        "WHERE relation.oid=%s::regclass AND privileges.grantee<>relation.relowner",
        (view,),
    )
    for row in await defaults.fetchall():
        role = sql.SQL("PUBLIC") if row["grantee"] == 0 else sql.Identifier(row["rolname"])
        await connection.execute(
            sql.SQL("REVOKE ALL ON {} FROM {}").format(sql.Identifier(view), role)
        )
    cursor = await connection.execute(
        "SELECT privileges.grantee, privileges.is_grantable, roles.rolname "
        "FROM pg_class AS relation "
        "CROSS JOIN LATERAL aclexplode(COALESCE(relation.relacl, "
        "acldefault('r',relation.relowner))) AS privileges "
        "LEFT JOIN pg_roles AS roles ON roles.oid=privileges.grantee "
        "WHERE relation.oid=%s::regclass AND privileges.privilege_type='SELECT'",
        (original,),
    )
    for row in await cursor.fetchall():
        role = sql.SQL("PUBLIC") if row["grantee"] == 0 else sql.Identifier(row["rolname"])
        await connection.execute(
            sql.SQL("GRANT SELECT ON {} TO {}{}").format(
                sql.Identifier(view),
                role,
                sql.SQL(" WITH GRANT OPTION" if row["is_grantable"] else ""),
            )
        )


async def _version_content(
    connection: psycopg.AsyncConnection[Any], version: str | None
) -> tuple[str, int, int]:
    await connection.execute("SELECT set_config('TimeZone','UTC',true)")
    digest = hashlib.sha256()
    counts: list[int] = []
    total_bytes = 0
    for table in _TABLES:
        count = 0
        order = "id" if table == "ontology_resource" else "from_id, link_type, to_id"
        query = sql.SQL(
            "SELECT (to_jsonb(record)-'snapshot_version')::text AS content "
            "FROM {} AS record "
            + ("WHERE snapshot_version=%s " if version is not None else "")
            + "ORDER BY "
            + order
        ).format(sql.Identifier(table + "_version" if version is not None else table))
        async with connection.cursor(name="ontology_version_seal") as cursor:
            await cursor.execute(query, (version,) if version is not None else ())
            async for row in cursor:
                content = row["content"].encode()
                total_bytes += len(content)
                count += 1
                if total_bytes > _MAX_BYTES or sum(counts) + count > _MAX_ROWS:
                    raise ValueError("ontology version exceeds its retained graph bounds")
                digest.update(table.encode() + b"\x00" + content + b"\n")
        counts.append(count)
    return "sha256:" + digest.hexdigest(), counts[0], counts[1]


async def _seal_version(connection: psycopg.AsyncConnection[Any], version: str) -> str:
    result, object_count, link_count = await _version_content(connection, version)
    await connection.execute(
        "UPDATE ontology_graph_version SET content_digest=%s, object_count=%s, "
        "link_count=%s, sealed=TRUE WHERE version_id=%s AND NOT sealed",
        (result, object_count, link_count, version),
    )
    return result


async def activate_versioned_graph(connection: psycopg.AsyncConnection[Any]) -> str:
    """Preserve legacy tables and read grants; callers own commit or rollback.

    The caller needs schema-owner privileges. Existing RLS, column grants and dependent
    views require a separately reviewed migration rather than silently changing access.
    No provider is contacted and this operation does not grant write authority.
    """
    if connection.autocommit:
        raise ValueError("ontology transition requires caller-owned transactions")
    await connection.execute("SELECT 1")
    async with asyncio.timeout(30), connection.transaction():
        await _lock_transition(connection, active=False)
        cursor = await connection.execute(
            "SELECT active_version FROM ontology_graph_control WHERE singleton FOR UPDATE"
        )
        control = await cursor.fetchone()
        if control is None or control["active_version"] is not None:
            raise ValueError("ontology version activation requires legacy storage")
        for table in _TABLES:
            cursor = await connection.execute(
                "SELECT relation.relrowsecurity OR relation.relforcerowsecurity OR EXISTS ("
                "SELECT 1 FROM pg_attribute WHERE attrelid=relation.oid AND attacl IS NOT NULL"
                ") OR EXISTS (SELECT 1 FROM pg_depend AS dependency JOIN pg_rewrite AS rewrite "
                "ON rewrite.oid=dependency.objid WHERE dependency.refobjid=relation.oid "
                "AND dependency.classid='pg_rewrite'::regclass) OR EXISTS ("
                "SELECT 1 FROM pg_trigger WHERE tgrelid=relation.oid AND NOT tgisinternal "
                "AND NOT tgname=ANY(%s::text[])) OR EXISTS ("
                "SELECT 1 FROM pg_constraint AS constraint_record "
                "WHERE constraint_record.contype='f' AND constraint_record.confrelid=relation.oid "
                "AND (relation.relname='ontology_link' "
                "OR cardinality(constraint_record.confkey)<>1 "
                "OR constraint_record.confkey[1]<>(SELECT attnum FROM pg_attribute "
                "WHERE attrelid=relation.oid AND attname='id'))) AS unsupported "
                "FROM pg_class AS relation WHERE relation.oid=%s::regclass",
                (
                    [
                        table + suffix
                        for suffix in (
                            "_writer_protocol",
                            "_writer_update_protocol",
                            "_version_fence",
                            "_version_update_fence",
                        )
                    ],
                    table,
                ),
            )
            access = await cursor.fetchone()
            if access is None or access["unsupported"]:
                raise ValueError("ontology activation requires dependency and access migration")
        version = uuid.uuid4().hex
        await connection.execute(
            "INSERT INTO ontology_graph_version (version_id) VALUES (%s)", (version,)
        )
        for table in _TABLES:
            columns = sql.SQL(", ").join(map(sql.Identifier, await _columns(connection, table)))
            await connection.execute(
                sql.SQL("INSERT INTO {} (snapshot_version, {}) SELECT %s, {} FROM {}").format(
                    sql.Identifier(table + "_version"), columns, columns, sql.Identifier(table)
                ),
                (version,),
            )
        digest = await _seal_version(connection, version)
        await connection.execute(
            "UPDATE state_kv SET value=jsonb_build_object('schema_version','1.0.0',"
            "'minimum_writer_version',2) WHERE key='ontology:writer-protocol'"
        )
        await connection.execute(
            "UPDATE ontology_graph_control SET active_version=%s, epoch=epoch+1 WHERE singleton",
            (version,),
        )
        for table in _TABLES:
            columns = sql.SQL(", ").join(map(sql.Identifier, await _columns(connection, table)))
            await connection.execute(
                sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                    sql.Identifier(table), sql.Identifier(table + "_legacy")
                )
            )
            await connection.execute(
                sql.SQL(
                    "CREATE VIEW {} AS SELECT {} FROM {} WHERE snapshot_version="
                    "(SELECT active_version FROM ontology_graph_control WHERE singleton)"
                ).format(sql.Identifier(table), columns, sql.Identifier(table + "_version"))
            )
            await _copy_read_grants(connection, original=table + "_legacy", view=table)
        return digest


async def materialize_legacy_graph(connection: psycopg.AsyncConnection[Any]) -> None:
    """Restore current version contents, not the old backup, in one caller-owned transaction."""
    if connection.autocommit:
        raise ValueError("ontology transition requires caller-owned transactions")
    await connection.execute("SELECT 1")
    async with asyncio.timeout(30), connection.transaction():
        await _lock_transition(connection, active=True)
        cursor = await connection.execute(
            "SELECT active_version FROM ontology_graph_control WHERE singleton FOR UPDATE"
        )
        control = await cursor.fetchone()
        if control is None or control["active_version"] is None:
            raise ValueError("ontology materialization requires an active version")
        version = control["active_version"]
        cursor = await connection.execute(
            "SELECT content_digest, object_count, link_count FROM ontology_graph_version "
            "WHERE version_id=%s AND sealed FOR SHARE",
            (version,),
        )
        receipt = await cursor.fetchone()
        if receipt is None or await _version_content(connection, version) != (
            receipt["content_digest"],
            receipt["object_count"],
            receipt["link_count"],
        ):
            raise ValueError("ontology materialization requires verified version content")
        await connection.execute("SELECT set_config('fdai.ontology_materialization','on',true)")
        await connection.execute("DELETE FROM ontology_link_legacy")
        resource_columns = await _columns(connection, "ontology_resource_legacy")
        columns = sql.SQL(", ").join(map(sql.Identifier, resource_columns))
        updates = sql.SQL(", ").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
            for name in resource_columns
            if name != "id"
        )
        await connection.execute(
            sql.SQL(
                "INSERT INTO ontology_resource_legacy ({}) SELECT {} FROM ontology_resource "
                "ON CONFLICT (id) DO UPDATE SET {}"
            ).format(columns, columns, updates)
        )
        await connection.execute(
            "DELETE FROM ontology_resource_legacy "
            "WHERE id NOT IN (SELECT id FROM ontology_resource)"
        )
        columns = sql.SQL(", ").join(
            map(sql.Identifier, await _columns(connection, "ontology_link_legacy"))
        )
        await connection.execute(
            sql.SQL("INSERT INTO ontology_link_legacy ({}) SELECT {} FROM ontology_link").format(
                columns, columns
            )
        )
        for table in reversed(_TABLES):
            await connection.execute(sql.SQL("DROP VIEW {}").format(sql.Identifier(table)))
        for table in _TABLES:
            await connection.execute(
                sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                    sql.Identifier(table + "_legacy"), sql.Identifier(table)
                )
            )
        await connection.execute(
            "UPDATE ontology_graph_control SET active_version=NULL, epoch=epoch+1 WHERE singleton"
        )
        await connection.execute(
            "UPDATE state_kv SET value=jsonb_build_object('schema_version','1.0.0',"
            "'minimum_writer_version',1) WHERE key='ontology:writer-protocol'"
        )
        await connection.execute("SELECT set_config('fdai.ontology_materialization','',true)")
