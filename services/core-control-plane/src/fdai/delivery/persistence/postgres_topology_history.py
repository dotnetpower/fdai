"""PostgreSQL adapter for append-only bitemporal topology history."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.ontology_platform.topology_history import (
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
)

_MAX_BATCHES: Final[int] = 1_000
_MAX_REVISIONS: Final[int] = 20_000


@dataclass(frozen=True, slots=True)
class PostgresTopologyHistoryStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresTopologyHistoryStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")


class PostgresTopologyHistoryStore:
    """Atomically append and boundedly read immutable topology revisions."""

    def __init__(self, *, config: PostgresTopologyHistoryStoreConfig) -> None:
        self._config = config

    async def append(
        self,
        batch: TopologyRevisionBatch,
        *,
        ontology_release_digest: str,
        source_receipt_digest: str,
    ) -> None:
        """Insert one batch and all of its children in one transaction."""

        _validate_digest(ontology_release_digest, "ontology_release_digest")
        _validate_digest(source_receipt_digest, "source_receipt_digest")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "INSERT INTO topology_revision_batch "
                    "(revision_id, provider_generation_ref, ontology_release_digest, "
                    "source_receipt_digest, effective_at, recorded_at, complete_snapshot) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        batch.revision_id,
                        batch.provider_generation_ref,
                        ontology_release_digest,
                        source_receipt_digest,
                        batch.effective_at,
                        batch.recorded_at,
                        batch.complete_snapshot,
                    ),
                )
                if batch.object_revisions:
                    async with connection.cursor() as cursor:
                        await cursor.executemany(
                            "INSERT INTO topology_object_revision "
                            "(revision_id, object_id, object_type, properties, effective_at, "
                            "recorded_at, deleted, evidence_ref) "
                            "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)",
                            [
                                (
                                    batch.revision_id,
                                    item.object_id,
                                    item.object_type,
                                    item.properties_json,
                                    item.effective_at,
                                    item.recorded_at,
                                    item.deleted,
                                    item.evidence_ref,
                                )
                                for item in batch.object_revisions
                            ],
                        )
                if batch.link_revisions:
                    async with connection.cursor() as cursor:
                        await cursor.executemany(
                            "INSERT INTO topology_link_revision "
                            "(revision_id, from_id, from_type, link_type, to_id, to_type, "
                            "properties, effective_at, recorded_at, deleted, evidence_ref) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)",
                            [
                                (
                                    batch.revision_id,
                                    item.from_id,
                                    item.from_type,
                                    item.link_type,
                                    item.to_id,
                                    item.to_type,
                                    item.properties_json,
                                    item.effective_at,
                                    item.recorded_at,
                                    item.deleted,
                                    item.evidence_ref,
                                )
                                for item in batch.link_revisions
                            ],
                        )

    async def read(
        self,
        *,
        as_of: datetime,
        known_at: datetime,
    ) -> Sequence[TopologyRevisionBatch]:
        """Read revisions visible at both event-time and record-time cutoffs."""

        _validate_cutoff(as_of, known_at)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                batch_cursor = await connection.execute(
                    "SELECT revision_id, provider_generation_ref, effective_at, recorded_at, "
                    "complete_snapshot FROM topology_revision_batch "
                    "WHERE effective_at <= %s AND recorded_at <= %s "
                    "ORDER BY recorded_at, revision_id LIMIT 1001",
                    (as_of, known_at),
                )
                batch_rows = await batch_cursor.fetchall()
                if len(batch_rows) > _MAX_BATCHES:
                    raise ValueError(f"topology history exceeds {_MAX_BATCHES} batches")
                if not batch_rows:
                    return ()
                revision_ids = [str(row["revision_id"]) for row in batch_rows]
                object_cursor = await connection.execute(
                    "SELECT revision_id, object_id, object_type, properties, effective_at, "
                    "recorded_at, deleted, evidence_ref FROM topology_object_revision "
                    "WHERE revision_id = ANY(%s) "
                    "ORDER BY revision_id, object_id LIMIT 20001",
                    (revision_ids,),
                )
                object_rows = await object_cursor.fetchall()
                link_cursor = await connection.execute(
                    "SELECT revision_id, from_id, from_type, link_type, to_id, to_type, "
                    "properties, effective_at, recorded_at, deleted, evidence_ref "
                    "FROM topology_link_revision WHERE revision_id = ANY(%s) "
                    "ORDER BY revision_id, from_id, link_type, to_id LIMIT 20001",
                    (revision_ids,),
                )
                link_rows = await link_cursor.fetchall()
        if len(object_rows) + len(link_rows) > _MAX_REVISIONS:
            raise ValueError(f"topology history exceeds {_MAX_REVISIONS} revisions")
        return _reconstruct_batches(batch_rows, object_rows, link_rows)

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=False,
            connect_timeout=self._config.connect_timeout_s,
            row_factory=dict_row,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _reconstruct_batches(
    batch_rows: Sequence[Mapping[str, Any]],
    object_rows: Sequence[Mapping[str, Any]],
    link_rows: Sequence[Mapping[str, Any]],
) -> tuple[TopologyRevisionBatch, ...]:
    objects: dict[str, list[TopologyObjectRevision]] = {}
    for row in object_rows:
        objects.setdefault(str(row["revision_id"]), []).append(
            TopologyObjectRevision(
                object_id=str(row["object_id"]),
                object_type=str(row["object_type"]),
                properties_json=_canonical_properties(row["properties"]),
                effective_at=row["effective_at"],
                recorded_at=row["recorded_at"],
                deleted=bool(row["deleted"]),
                evidence_ref=str(row["evidence_ref"]),
            )
        )
    links: dict[str, list[TopologyLinkRevision]] = {}
    for row in link_rows:
        links.setdefault(str(row["revision_id"]), []).append(
            TopologyLinkRevision(
                from_id=str(row["from_id"]),
                from_type=str(row["from_type"]),
                link_type=str(row["link_type"]),
                to_id=str(row["to_id"]),
                to_type=str(row["to_type"]),
                properties_json=_canonical_properties(row["properties"]),
                effective_at=row["effective_at"],
                recorded_at=row["recorded_at"],
                deleted=bool(row["deleted"]),
                evidence_ref=str(row["evidence_ref"]),
            )
        )
    return tuple(
        TopologyRevisionBatch(
            revision_id=str(row["revision_id"]),
            provider_generation_ref=str(row["provider_generation_ref"]),
            effective_at=row["effective_at"],
            recorded_at=row["recorded_at"],
            complete_snapshot=bool(row["complete_snapshot"]),
            object_revisions=tuple(objects.get(str(row["revision_id"]), ())),
            link_revisions=tuple(links.get(str(row["revision_id"]), ())),
        )
        for row in batch_rows
    )


def _canonical_properties(value: object) -> str:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise ValueError("topology revision properties MUST be a JSON object")
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _validate_cutoff(as_of: datetime, known_at: datetime) -> None:
    if as_of.tzinfo is None or known_at.tzinfo is None:
        raise ValueError("topology history cutoffs MUST be timezone-aware")
    if as_of > known_at:
        raise ValueError("topology as_of MUST NOT exceed known_at")


def _validate_digest(value: str, name: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a canonical SHA-256 digest")


__all__ = ["PostgresTopologyHistoryStore", "PostgresTopologyHistoryStoreConfig"]
