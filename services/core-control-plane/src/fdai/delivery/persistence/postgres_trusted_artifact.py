"""PostgreSQL revision-CAS persistence for trusted extensions and skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.supply_chain import (
    TrustedArtifactConflictError,
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)

_COLUMNS: Final = (
    "artifact_kind, artifact_id, version, source, content_sha256, artifact, signature, "
    "state, revision, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class PostgresTrustedArtifactStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresTrustedArtifactStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresTrustedArtifactStoreConfig timeouts MUST be positive")


class PostgresTrustedArtifactStore:
    """Persist current trusted artifact versions with exact revision updates."""

    def __init__(self, *, config: PostgresTrustedArtifactStoreConfig) -> None:
        self._config = config

    async def put(
        self,
        record: TrustedArtifactRecord,
        *,
        expected_revision: int,
    ) -> TrustedArtifactRecord:
        if expected_revision < 0 or record.revision != expected_revision + 1:
            raise ValueError("trusted artifact revision MUST equal expected_revision + 1")
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            if expected_revision == 0:
                cursor = await connection.execute(
                    f"""
                    INSERT INTO trusted_artifact ({_COLUMNS})
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (artifact_kind, artifact_id) DO NOTHING
                    RETURNING {_COLUMNS}
                    """,  # noqa: S608 - _COLUMNS is a module constant
                    _values(record),
                )
            else:
                cursor = await connection.execute(
                    f"""
                    UPDATE trusted_artifact
                       SET version = %s, source = %s, content_sha256 = %s,
                           artifact = %s, signature = %s, state = %s,
                           revision = %s, updated_at = %s
                     WHERE artifact_kind = %s AND artifact_id = %s AND revision = %s
                     RETURNING {_COLUMNS}
                    """,  # noqa: S608 - _COLUMNS is a module constant
                    (
                        record.version,
                        record.source,
                        record.content_sha256,
                        record.artifact,
                        record.signature,
                        record.state.value,
                        record.revision,
                        record.updated_at,
                        record.kind.value,
                        record.artifact_id,
                        expected_revision,
                    ),
                )
            row = await cursor.fetchone()
        if row is None:
            raise TrustedArtifactConflictError(
                "trusted artifact revision mismatch or record already exists"
            )
        return _row_to_record(row)

    async def get(
        self,
        kind: TrustedArtifactKind,
        artifact_id: str,
    ) -> TrustedArtifactRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trusted_artifact "  # noqa: S608
                "WHERE artifact_kind = %s AND artifact_id = %s",
                (kind.value, artifact_id),
            )
            row = await cursor.fetchone()
        return _row_to_record(row) if row is not None else None

    async def list(self, kind: TrustedArtifactKind) -> tuple[TrustedArtifactRecord, ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM trusted_artifact "  # noqa: S608
                "WHERE artifact_kind = %s ORDER BY artifact_id",
                (kind.value,),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_record(row) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _values(record: TrustedArtifactRecord) -> tuple[object, ...]:
    return (
        record.kind.value,
        record.artifact_id,
        record.version,
        record.source,
        record.content_sha256,
        record.artifact,
        record.signature,
        record.state.value,
        record.revision,
        record.created_at,
        record.updated_at,
    )


def _row_to_record(row: dict[str, Any]) -> TrustedArtifactRecord:
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind(str(row["artifact_kind"])),
        artifact_id=str(row["artifact_id"]),
        version=str(row["version"]),
        source=str(row["source"]),
        content_sha256=str(row["content_sha256"]),
        artifact=bytes(row["artifact"]),
        signature=bytes(row["signature"]),
        state=TrustedArtifactState(str(row["state"])),
        revision=int(row["revision"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["PostgresTrustedArtifactStore", "PostgresTrustedArtifactStoreConfig"]
