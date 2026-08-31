"""PostgreSQL integrity and smoke adapters for DB-DR verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from fdai.shared.providers.db_dr import (
    DbDrError,
    DbRestoreHandle,
    IntegrityMismatch,
    IntegrityMismatchKind,
    IntegrityReport,
    SmokeCheck,
    SmokeReport,
)

_TABLE_NAME: Final[re.Pattern[str]] = re.compile(
    r"^[a-z_][a-z0-9_]{0,62}(?:\.[a-z_][a-z0-9_]{0,62})?$"
)


@dataclass(frozen=True, slots=True)
class PostgresDbDrSettings:
    """Configure bounded source-to-restored PostgreSQL checks."""

    source_dsn: str
    tables: tuple[str, ...]
    connect_timeout_seconds: int = 10
    statement_timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.source_dsn.strip():
            raise ValueError("source_dsn MUST be non-empty")
        if not self.tables or len(self.tables) > 16:
            raise ValueError("tables MUST contain between 1 and 16 names")
        if self.tables != tuple(sorted(set(self.tables))):
            raise ValueError("tables MUST be unique and ordered")
        if any(_TABLE_NAME.fullmatch(table) is None for table in self.tables):
            raise ValueError("tables contains an invalid PostgreSQL identifier")
        if self.connect_timeout_seconds < 1 or self.statement_timeout_seconds < 1:
            raise ValueError("PostgreSQL DB-DR timeouts MUST be positive")


class PostgresIntegrityChecker:
    """Compare bounded table counts and deterministic row-content checksums."""

    def __init__(self, *, settings: PostgresDbDrSettings) -> None:
        self._settings = settings

    async def check(self, handle: DbRestoreHandle) -> IntegrityReport:
        try:
            source = await _table_snapshot(
                self._settings.source_dsn,
                tables=self._settings.tables,
                settings=self._settings,
            )
            restored = await _table_snapshot(
                _target_dsn(self._settings.source_dsn, handle.endpoint),
                tables=self._settings.tables,
                settings=self._settings,
            )
        except (psycopg.Error, ValueError) as exc:
            raise DbDrError(
                "PostgreSQL integrity check failed",
                experiment_id=handle.experiment_id,
                phase="integrity",
            ) from exc
        mismatches: list[IntegrityMismatch] = []
        for table in self._settings.tables:
            source_count, source_checksum = source[table]
            restored_count, restored_checksum = restored[table]
            if source_count != restored_count:
                mismatches.append(
                    IntegrityMismatch(
                        kind=IntegrityMismatchKind.ROW_COUNT,
                        table=table,
                        detail="source and restored row counts differ",
                    )
                )
            if source_checksum != restored_checksum:
                mismatches.append(
                    IntegrityMismatch(
                        kind=IntegrityMismatchKind.CHECKSUM,
                        table=table,
                        detail="source and restored row checksums differ",
                    )
                )
        return IntegrityReport(
            table_row_counts={table: restored[table][0] for table in self._settings.tables},
            checksums={table: restored[table][1] for table in self._settings.tables},
            mismatches=tuple(mismatches),
        )


class PostgresSmokeRunner:
    """Run one read and one rolled-back write against the restored server."""

    def __init__(self, *, settings: PostgresDbDrSettings) -> None:
        self._settings = settings

    async def run(self, handle: DbRestoreHandle) -> SmokeReport:
        try:
            dsn = _target_dsn(self._settings.source_dsn, handle.endpoint)
            async with await psycopg.AsyncConnection.connect(
                dsn,
                connect_timeout=self._settings.connect_timeout_seconds,
                options=(f"-c statement_timeout={self._settings.statement_timeout_seconds * 1000}"),
            ) as connection:
                read_cursor = await connection.execute("SELECT 1")
                read_row = await read_cursor.fetchone()
                await connection.execute(
                    "CREATE TEMP TABLE fdai_db_dr_smoke (value integer NOT NULL) ON COMMIT DROP"
                )
                await connection.execute("INSERT INTO fdai_db_dr_smoke (value) VALUES (1)")
                write_cursor = await connection.execute("SELECT value FROM fdai_db_dr_smoke")
                write_row = await write_cursor.fetchone()
                await connection.rollback()
        except (psycopg.Error, ValueError) as exc:
            raise DbDrError(
                "PostgreSQL smoke check failed",
                experiment_id=handle.experiment_id,
                phase="smoke",
            ) from exc
        return SmokeReport(
            checks=(
                SmokeCheck(name="read", passed=read_row == (1,)),
                SmokeCheck(name="rolled-back-write", passed=write_row == (1,)),
            )
        )


async def _table_snapshot(
    dsn: str,
    *,
    tables: tuple[str, ...],
    settings: PostgresDbDrSettings,
) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    async with await psycopg.AsyncConnection.connect(
        dsn,
        connect_timeout=settings.connect_timeout_seconds,
        options=f"-c statement_timeout={settings.statement_timeout_seconds * 1000}",
    ) as connection:
        for table in tables:
            identifier = sql.Identifier(*table.split(".", maxsplit=1))
            query = sql.SQL(
                """
                SELECT count(*)::bigint,
                       encode(
                           sha256(
                               convert_to(
                                   COALESCE(string_agg(row_value, '' ORDER BY row_value), ''),
                                   'UTF8'
                               )
                           ),
                           'hex'
                       )
                FROM (
                    SELECT to_jsonb(source_row)::text AS row_value
                    FROM {} AS source_row
                ) AS rows
                """
            ).format(identifier)
            cursor = await connection.execute(query)
            row = await cursor.fetchone()
            if (
                row is None
                or len(row) != 2
                or not isinstance(row[0], int)
                or not isinstance(row[1], str)
            ):
                raise ValueError("PostgreSQL integrity query returned an invalid row")
            snapshot[table] = (row[0], row[1])
        await connection.rollback()
    return snapshot


def _target_dsn(source_dsn: str, endpoint: str) -> str:
    if not endpoint.strip() or any(character.isspace() for character in endpoint):
        raise ValueError("restored PostgreSQL endpoint MUST be non-empty")
    normalized = source_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    return str(make_conninfo(normalized, host=endpoint))


__all__ = [
    "PostgresDbDrSettings",
    "PostgresIntegrityChecker",
    "PostgresSmokeRunner",
]
