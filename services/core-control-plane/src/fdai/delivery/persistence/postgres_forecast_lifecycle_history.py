"""Read-only incarnation-ledger pages for forecast resource-lifecycle history.

Deletion comes only from confirmed tombstones that closed an incarnation, and recreation only
from a later incarnation boundary. Absence from a generation, an unconfirmed tombstone, or an
empty page never becomes a deletion. Record times come from the originating journal rows so the
reader can answer as known at a cutoff instead of trusting the mutable ledger row alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

_MAX_INCARNATIONS = 64
_MAX_WINDOW = timedelta(days=31)


@dataclass(frozen=True, slots=True)
class LifecycleIncarnationRow:
    """One ledger boundary with journal-backed record times; `None` means not yet known."""

    incarnation_id: str
    opened_at: datetime
    opened_recorded_at: datetime | None
    opening_observation_id: str
    closed_at: datetime | None
    closed_recorded_at: datetime | None
    closing_observation_id: str | None


@dataclass(frozen=True, slots=True)
class LifecycleLedgerRead:
    incarnations: tuple[LifecycleIncarnationRow, ...]
    pending_tombstone_ids: tuple[str, ...]
    truncated: bool
    snapshot_ref: str


@dataclass(frozen=True, slots=True)
class PostgresForecastLifecycleHistoryConfig:
    dsn: str
    statement_timeout_ms: int = 3_000
    connect_timeout_s: int = 3

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("forecast lifecycle history DSN MUST NOT be empty")
        if not 1 <= self.statement_timeout_ms <= 10_000 or not 1 <= self.connect_timeout_s <= 10:
            raise ValueError("forecast lifecycle history database deadlines are out of bounds")


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


class PostgresForecastLifecycleHistoryReader:
    """Read one exact subject's incarnations in one repeatable-read snapshot."""

    def __init__(self, *, config: PostgresForecastLifecycleHistoryConfig) -> None:
        self._config = config

    async def read_ledger(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
    ) -> LifecycleLedgerRead:
        if not subject_ref or subject_ref != subject_ref.strip() or len(subject_ref) > 512:
            raise ValueError("forecast lifecycle history requires one exact bounded subject")
        if not all(_aware(value) for value in (start_at, end_at, known_at)):
            raise ValueError("forecast lifecycle history times MUST be timezone-aware")
        if not start_at <= end_at <= known_at or end_at - start_at > _MAX_WINDOW:
            raise ValueError("forecast lifecycle history window is not causally bounded")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT * FROM (SELECT incarnation.incarnation_id, incarnation.opened_at, "
                "incarnation.closed_at, incarnation.opening_observation_id, "
                "incarnation.closing_observation_id, opening.recorded_at AS opened_recorded_at, "
                "closing.recorded_at AS closed_recorded_at "
                "FROM inventory_resource_incarnation AS incarnation "
                "LEFT JOIN inventory_observation_journal AS opening "
                "ON opening.observation_id = incarnation.opening_observation_id "
                "LEFT JOIN inventory_observation_journal AS closing "
                "ON closing.observation_id = incarnation.closing_observation_id "
                "WHERE incarnation.resource_ref = %s AND incarnation.opened_at <= %s "
                "ORDER BY incarnation.opened_at DESC, incarnation.incarnation_id DESC LIMIT %s"
                ") AS newest ORDER BY opened_at, incarnation_id",
                (subject_ref, end_at, _MAX_INCARNATIONS + 1),
            )
            rows = await cursor.fetchall()
            pending_cursor = await connection.execute(
                "SELECT observation_id FROM inventory_observation_pending_tombstone "
                "WHERE resource_id = %s AND recorded_at <= %s ORDER BY observation_id LIMIT 16",
                (subject_ref, known_at),
            )
            pending = tuple(str(row["observation_id"]) for row in await pending_cursor.fetchall())
        truncated = len(rows) > _MAX_INCARNATIONS
        incarnations = tuple(_row(row) for row in (rows[1:] if truncated else rows))
        return LifecycleLedgerRead(
            incarnations=incarnations,
            pending_tombstone_ids=pending,
            truncated=truncated,
            snapshot_ref="inventory-incarnation-ledger:" + _ledger_digest(incarnations, pending),
        )


def _ledger_digest(
    incarnations: tuple[LifecycleIncarnationRow, ...], pending: tuple[str, ...]
) -> str:
    """Fence the exact rows read so identical replays retain one identical checkpoint."""
    body = [
        [
            item.incarnation_id,
            item.opened_at.isoformat(),
            item.opened_recorded_at.isoformat() if item.opened_recorded_at else None,
            item.closed_at.isoformat() if item.closed_at else None,
            item.closed_recorded_at.isoformat() if item.closed_recorded_at else None,
            item.closing_observation_id,
        ]
        for item in incarnations
    ]
    encoded = json.dumps([body, list(pending)], separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _row(row: dict[str, Any]) -> LifecycleIncarnationRow:
    opened_at, closed_at = row["opened_at"], row["closed_at"]
    if not _aware(opened_at) or (closed_at is not None and not _aware(closed_at)):
        raise ValueError("forecast lifecycle incarnation times MUST be timezone-aware")
    for name in ("opened_recorded_at", "closed_recorded_at"):
        if row[name] is not None and not _aware(row[name]):
            raise ValueError("forecast lifecycle journal record times MUST be timezone-aware")
    return LifecycleIncarnationRow(
        incarnation_id=str(row["incarnation_id"]),
        opened_at=opened_at,
        opened_recorded_at=row["opened_recorded_at"],
        opening_observation_id=str(row["opening_observation_id"]),
        closed_at=closed_at,
        closed_recorded_at=row["closed_recorded_at"],
        closing_observation_id=(
            str(row["closing_observation_id"])
            if row["closing_observation_id"] is not None
            else None
        ),
    )


__all__ = [
    "LifecycleIncarnationRow",
    "LifecycleLedgerRead",
    "PostgresForecastLifecycleHistoryConfig",
    "PostgresForecastLifecycleHistoryReader",
]
