"""PostgreSQL report-line draft projection for the ingestion API."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts import DocumentNotFoundError, ReportingLineDraftArtifact
from psycopg.rows import dict_row


class PostgresReportingLineDraftReader:
    """Read one worker-produced report-line draft without mutation authority."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        if not dsn:
            raise ValueError("reporting-line draft PostgreSQL DSN MUST NOT be empty")
        if connect_timeout_s < 1:
            raise ValueError("reporting-line draft connect timeout MUST be positive")
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def get(self, upload_id: UUID) -> ReportingLineDraftArtifact:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    (f"report_line_draft:{upload_id}",),
                )
            ).fetchone()
        if row is None:
            raise DocumentNotFoundError("reporting-line draft was not found")
        value: Any = row["value"]
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise RuntimeError("durable reporting-line draft is malformed")
        return ReportingLineDraftArtifact.model_validate(value)


__all__ = ["PostgresReportingLineDraftReader"]
