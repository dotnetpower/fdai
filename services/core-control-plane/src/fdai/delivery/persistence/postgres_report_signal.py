"""Durable report-feed signal projection on PostgreSQL."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.report_feed.models import ReportCategory, ReportSignal, SignalKind
from fdai.shared.contracts.models import Severity


@dataclass(frozen=True, slots=True)
class PostgresReportSignalStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresReportSignalStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")


class PostgresReportSignalStore:
    """Idempotent signal writer and live report-feed source."""

    name = "postgres-report-signal"

    def __init__(self, *, config: PostgresReportSignalStoreConfig) -> None:
        self._config: Final[PostgresReportSignalStoreConfig] = config

    async def record(self, signal: ReportSignal) -> None:
        await self.record_many((signal,))

    async def record_many(self, signals: Sequence[ReportSignal]) -> None:
        if not signals:
            return
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                for signal in signals:
                    await connection.execute(
                        """
                        INSERT INTO report_signal (
                            signal_id, kind, category, severity, resource_ref,
                            title, detail, occurred_at, evidence_refs, metadata
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (signal_id) DO NOTHING
                        """,
                        (
                            signal.signal_id,
                            signal.kind.value,
                            signal.category.value,
                            signal.severity.value,
                            signal.resource_ref,
                            signal.title,
                            signal.detail,
                            signal.occurred_at,
                            json.dumps(list(signal.evidence_refs)),
                            json.dumps(dict(signal.metadata)),
                        ),
                    )

    async def signals(self, *, since: datetime, until: datetime) -> Sequence[ReportSignal]:
        async with await self._connect(row_factory=True) as connection:
            await self._set_statement_timeout(connection)
            cursor = await connection.execute(
                """
                SELECT signal_id, kind, category, severity, resource_ref,
                       title, detail, occurred_at, evidence_refs, metadata
                  FROM report_signal
                 WHERE occurred_at >= %s AND occurred_at <= %s
                 ORDER BY occurred_at DESC, signal_id
                """,
                (since, until),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_signal(row) for row in rows)

    async def _connect(self, *, row_factory: bool = False) -> psycopg.AsyncConnection[Any]:
        kwargs: dict[str, Any] = {"connect_timeout": self._config.connect_timeout_s}
        if row_factory:
            kwargs["row_factory"] = dict_row
        return await psycopg.AsyncConnection.connect(self._config.dsn, **kwargs)

    async def _set_statement_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout_ms = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout_ms}")


def _row_to_signal(row: dict[str, Any]) -> ReportSignal:
    evidence = _json_value(row["evidence_refs"])
    metadata = _json_value(row["metadata"])
    return ReportSignal(
        signal_id=str(row["signal_id"]),
        kind=SignalKind(str(row["kind"])),
        category=ReportCategory(str(row["category"])),
        severity=Severity(str(row["severity"])),
        resource_ref=str(row["resource_ref"]),
        title=str(row["title"]),
        detail=str(row["detail"]),
        occurred_at=row["occurred_at"],
        evidence_refs=tuple(str(item) for item in evidence) if isinstance(evidence, list) else (),
        metadata=(
            {str(key): str(value) for key, value in metadata.items()}
            if isinstance(metadata, dict)
            else {}
        ),
    )


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["PostgresReportSignalStore", "PostgresReportSignalStoreConfig"]
