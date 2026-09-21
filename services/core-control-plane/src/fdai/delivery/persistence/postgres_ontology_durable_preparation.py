"""Restartable verified relational candidates, separate from atomic graph publication."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.delivery.persistence.postgres_ontology_prepared import (
    PreparedOntologyReplacement,
    _digest,
    _encode,
    restore_replacement,
    verify_replacement_content,
    verify_replacement_dependencies,
)
from fdai.delivery.persistence.postgres_ontology_publication import versioned_storage_active
from fdai.delivery.persistence.postgres_ontology_replacement import replace_records
from fdai.delivery.persistence.postgres_ontology_transition import _version_content
from fdai.delivery.persistence.postgres_ontology_version_retention import prune_graph_versions
from fdai.delivery.persistence.postgres_ontology_version_writer import (
    VersionedGraphWrite,
    begin_versioned_write,
    seal_versioned_write,
)
from fdai.shared.contracts.models import OntologyLinkType, OntologyRelease
from fdai.shared.providers.ontology_instance import OntologyInstanceValidationError

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres_ontology import PostgresOntologyInstanceStoreConfig

_PREFIX = "ontology-version-prepared:"
_MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DurableOntologyPreparation:
    write: VersionedGraphWrite
    revisions: Mapping[str, int]
    receipt: str


async def consume_preparation(
    connection: psycopg.AsyncConnection[Any],
    prepared: PreparedOntologyReplacement,
    durable: DurableOntologyPreparation,
) -> None:
    """Release the pending pin atomically with publication; failed CAS restores it."""
    cursor = await connection.execute(
        "DELETE FROM state_kv WHERE key=%s "
        "AND updated_at>=clock_timestamp()-INTERVAL '30 minutes' RETURNING value",
        (_PREFIX + prepared.digest,),
    )
    row = await cursor.fetchone()
    if (
        row is None
        or not isinstance(row["value"], dict)
        or _encode(row["value"], limit=_MAX_BYTES) != durable.receipt
        or (
            row["value"].get("base_version"),
            row["value"].get("base_epoch"),
            row["value"].get("version"),
            row["value"].get("revisions"),
        )
        != (
            durable.write.base_version,
            durable.write.base_epoch,
            durable.write.prepared_version,
            durable.revisions,
        )
    ):
        raise OntologyInstanceValidationError(
            "durable ontology preparation changed before publication"
        )


async def prepare_inventory_version(
    config: PostgresOntologyInstanceStoreConfig,
    prepared: PreparedOntologyReplacement,
    *,
    releases: Mapping[str, OntologyRelease],
    link_types: Mapping[str, OntologyLinkType],
) -> DurableOntologyPreparation | None:
    """Commit or reuse one complete candidate; never move graph, state or delivery pointers."""
    manifest, objects, links = restore_replacement(prepared, expected_digest=prepared.digest)
    await prune_graph_versions(config)
    async with (
        asyncio.timeout(60),
        await psycopg.AsyncConnection.connect(
            config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
        ) as connection,
    ):
        await connection.execute(
            "SELECT set_config('statement_timeout',%s,true)", (str(config.statement_timeout_ms),)
        )
        if not await versioned_storage_active(connection):
            return None
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (_PREFIX + prepared.digest,)
        )
        await verify_replacement_content(connection, prepared)
        await verify_replacement_dependencies(connection, manifest)
        await connection.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_004,))
        cursor = await connection.execute(
            "SELECT value,updated_at>clock_timestamp()-INTERVAL '30 minutes' AS current "
            "FROM state_kv WHERE key=%s FOR UPDATE",
            (_PREFIX + prepared.digest,),
        )
        row = await cursor.fetchone()
        if row is not None:
            return await _restore_preparation(
                connection, row["value"], prepared.digest, current=row["current"]
            )
        cursor = await connection.execute(
            "SELECT count(*) AS count FROM state_kv WHERE starts_with(key,%s)", (_PREFIX,)
        )
        capacity = await cursor.fetchone()
        if capacity is None or capacity["count"] >= 16:
            raise OntologyInstanceValidationError(
                "durable ontology preparation capacity is exhausted"
            )
        write = await begin_versioned_write(connection)
        if write is None:
            raise OntologyInstanceValidationError("ontology storage changed during preparation")
        revisions = await replace_records(
            connection,
            objects=objects,
            links=links,
            previous_object_ids=manifest["previous_object_ids"],
            previous_link_keys=[tuple(key) for key in manifest["previous_link_keys"]],
            releases=releases,
            link_types=link_types,
        )
        sealed = await seal_versioned_write(connection, write)
        content = {
            "schema_version": "1.0.0",
            "prepared_digest": prepared.digest,
            "base_version": sealed.base_version,
            "base_epoch": sealed.base_epoch,
            "version": sealed.prepared_version,
            "revisions": revisions,
        }
        content["digest"] = _digest(_encode(content, limit=_MAX_BYTES))
        await connection.execute(
            "INSERT INTO state_kv (key,value) VALUES (%s,%s)",
            (_PREFIX + prepared.digest, Jsonb(content)),
        )
        return DurableOntologyPreparation(sealed, revisions, _encode(content, limit=_MAX_BYTES))


async def _restore_preparation(
    connection: psycopg.AsyncConnection[Any], content: Any, digest: str, *, current: bool
) -> DurableOntologyPreparation:
    if (
        not current
        or not isinstance(content, dict)
        or set(content)
        != {
            "schema_version",
            "prepared_digest",
            "base_version",
            "base_epoch",
            "version",
            "revisions",
            "digest",
        }
        or content["schema_version"] != "1.0.0"
        or content["prepared_digest"] != digest
        or type(content["base_epoch"]) is not int
        or content["base_epoch"] < 0
        or any(
            not isinstance(content[key], str)
            or len(content[key]) != 32
            or any(character not in "0123456789abcdef" for character in content[key])
            for key in ("version", "base_version")
        )
        or not isinstance(content["revisions"], dict)
        or any(type(value) is not int or value < 1 for value in content["revisions"].values())
        or content["digest"]
        != _digest(
            _encode(
                {key: value for key, value in content.items() if key != "digest"}, limit=_MAX_BYTES
            )
        )
    ):
        raise OntologyInstanceValidationError("durable ontology preparation is invalid or expired")
    cursor = await connection.execute(
        "SELECT active_version,epoch FROM ontology_graph_control WHERE singleton"
    )
    control = await cursor.fetchone()
    if control is None or (control["active_version"], control["epoch"]) != (
        content["base_version"],
        content["base_epoch"],
    ):
        raise OntologyInstanceValidationError("durable ontology preparation base changed")
    cursor = await connection.execute(
        "SELECT content_digest,object_count,link_count FROM ontology_graph_version "
        "WHERE version_id=%s AND sealed FOR SHARE",
        (content["version"],),
    )
    receipt = await cursor.fetchone()
    if receipt is None or await _version_content(connection, content["version"]) != (
        receipt["content_digest"],
        receipt["object_count"],
        receipt["link_count"],
    ):
        raise OntologyInstanceValidationError("durable ontology preparation content is unavailable")
    return DurableOntologyPreparation(
        VersionedGraphWrite(content["base_version"], content["base_epoch"], content["version"]),
        content["revisions"],
        _encode(content, limit=_MAX_BYTES),
    )
