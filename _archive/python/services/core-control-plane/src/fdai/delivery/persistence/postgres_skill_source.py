"""PostgreSQL persistence for approved skill sources and refresh state."""

# ruff: noqa: S608 - SQL identifiers are module constants; runtime values are parametrized.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.skill_quarantine import SkillSourceRefreshState

_SOURCE_COLUMNS: Final = (
    "source_id, kind, location, trust_tier, owner, allowed_path, "
    "authentication_audience_ref, refresh_policy, refresh_interval_seconds, enabled"
)
_REFRESH_COLUMNS: Final = (
    "source_id, last_refresh_at, next_refresh_at, last_etag, last_revision, "
    "error_count, retry_at, last_error_kind"
)


@dataclass(frozen=True, slots=True)
class PostgresSkillSourceStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresSkillSourceStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Postgres skill source timeouts MUST be positive")


class _PostgresSkillSourceBase:
    def __init__(self, *, config: PostgresSkillSourceStoreConfig) -> None:
        self._config = config

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


class PostgresSkillSourceStore(_PostgresSkillSourceBase):
    async def put(self, source: SkillSource, *, now: datetime) -> SkillSource:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO skill_source ({_SOURCE_COLUMNS}, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (source_id) DO NOTHING "
                f"RETURNING {_SOURCE_COLUMNS}",  # noqa: S608
                (*_source_values(source), now, now),
            )
            row = await cursor.fetchone()
            if row is None:
                current = await connection.execute(
                    f"SELECT {_SOURCE_COLUMNS} FROM skill_source WHERE source_id = %s",  # noqa: S608
                    (source.source_id,),
                )
                row = await current.fetchone()
        if row is None or _source_from_row(row) != source:
            raise ValueError("skill source id conflicts with different registration")
        return source

    async def get(self, source_id: str) -> SkillSource | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_SOURCE_COLUMNS} FROM skill_source WHERE source_id = %s",  # noqa: S608
                (source_id,),
            )
            row = await cursor.fetchone()
        return _source_from_row(row) if row is not None else None

    async def list(self, *, enabled_only: bool = False) -> tuple[SkillSource, ...]:
        where = " WHERE enabled = TRUE" if enabled_only else ""
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_SOURCE_COLUMNS} FROM skill_source{where} ORDER BY source_id"  # noqa: S608
            )
            rows = await cursor.fetchall()
        return tuple(_source_from_row(row) for row in rows)

    async def set_enabled(
        self, source_id: str, *, enabled: bool, now: datetime
    ) -> SkillSource | None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE skill_source SET enabled = %s, updated_at = %s "
                f"WHERE source_id = %s RETURNING {_SOURCE_COLUMNS}",  # noqa: S608
                (enabled, now, source_id),
            )
            row = await cursor.fetchone()
        return _source_from_row(row) if row is not None else None


class PostgresSkillSourceRefreshStateStore(_PostgresSkillSourceBase):
    async def put(self, state: SkillSourceRefreshState) -> SkillSourceRefreshState:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO skill_source_refresh_state ({_REFRESH_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "last_refresh_at = EXCLUDED.last_refresh_at, "
                "next_refresh_at = EXCLUDED.next_refresh_at, "
                "last_etag = EXCLUDED.last_etag, last_revision = EXCLUDED.last_revision, "
                "error_count = EXCLUDED.error_count, retry_at = EXCLUDED.retry_at, "
                "last_error_kind = EXCLUDED.last_error_kind "
                f"RETURNING {_REFRESH_COLUMNS}",  # noqa: S608
                _refresh_values(state),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("skill refresh state upsert returned no row")
        return _refresh_from_row(row)

    async def get(self, source_id: str) -> SkillSourceRefreshState | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_REFRESH_COLUMNS} FROM skill_source_refresh_state WHERE source_id = %s",  # noqa: S608
                (source_id,),
            )
            row = await cursor.fetchone()
        return _refresh_from_row(row) if row is not None else None

    async def claim(
        self, *, source_id: str, now: datetime, hold_until: datetime
    ) -> SkillSourceRefreshState | None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO skill_source_refresh_state ({_REFRESH_COLUMNS}) "
                "VALUES (%s, NULL, %s, NULL, NULL, 0, NULL, NULL) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "next_refresh_at = EXCLUDED.next_refresh_at, retry_at = NULL "
                "WHERE (skill_source_refresh_state.retry_at IS NOT NULL "
                "AND skill_source_refresh_state.retry_at <= %s) "
                "OR (skill_source_refresh_state.retry_at IS NULL "
                "AND (skill_source_refresh_state.next_refresh_at IS NULL "
                "OR skill_source_refresh_state.next_refresh_at <= %s)) "
                f"RETURNING {_REFRESH_COLUMNS}",
                (source_id, hold_until, now, now),
            )
            row = await cursor.fetchone()
        return _refresh_from_row(row) if row is not None else None


def _source_values(source: SkillSource) -> tuple[object, ...]:
    return (
        source.source_id,
        source.kind.value,
        source.location,
        source.trust_tier.value,
        source.owner,
        source.allowed_path,
        source.authentication_audience_ref,
        source.refresh_policy.value,
        source.refresh_interval_seconds,
        source.enabled,
    )


def _source_from_row(row: dict[str, Any]) -> SkillSource:
    return SkillSource(
        source_id=str(row["source_id"]),
        kind=SkillSourceKind(str(row["kind"])),
        location=str(row["location"]),
        trust_tier=SkillSourceTrustTier(str(row["trust_tier"])),
        owner=str(row["owner"]),
        allowed_path=str(row["allowed_path"]),
        authentication_audience_ref=str(row["authentication_audience_ref"]),
        refresh_policy=SkillSourceRefreshPolicy(str(row["refresh_policy"])),
        refresh_interval_seconds=int(row["refresh_interval_seconds"]),
        enabled=bool(row["enabled"]),
    )


def _refresh_values(state: SkillSourceRefreshState) -> tuple[object, ...]:
    return (
        state.source_id,
        state.last_refresh_at,
        state.next_refresh_at,
        state.last_etag,
        state.last_revision,
        state.error_count,
        state.retry_at,
        state.last_error_kind,
    )


def _refresh_from_row(row: dict[str, Any]) -> SkillSourceRefreshState:
    return SkillSourceRefreshState(
        source_id=str(row["source_id"]),
        last_refresh_at=row["last_refresh_at"],
        next_refresh_at=row["next_refresh_at"],
        last_etag=str(row["last_etag"]) if row["last_etag"] is not None else None,
        last_revision=(str(row["last_revision"]) if row["last_revision"] is not None else None),
        error_count=int(row["error_count"]),
        retry_at=row["retry_at"],
        last_error_kind=(
            str(row["last_error_kind"]) if row["last_error_kind"] is not None else None
        ),
    )


__all__ = [
    "PostgresSkillSourceRefreshStateStore",
    "PostgresSkillSourceStore",
    "PostgresSkillSourceStoreConfig",
]
