"""PostgreSQL storage for worker-produced report-line drafts."""

from __future__ import annotations

import json

import psycopg
from fdai_service_contracts import ReportingLineDraftArtifact


class PostgresReportingLineDraftStore:
    """Upsert one review-only report-line draft into the shared state projection."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        if not dsn:
            raise ValueError("reporting-line draft PostgreSQL DSN MUST NOT be empty")
        if connect_timeout_s < 1:
            raise ValueError("reporting-line draft connect timeout MUST be positive")
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def put(self, artifact: ReportingLineDraftArtifact) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (
                    f"report_line_draft:{artifact.upload_id}",
                    json.dumps(artifact.to_dict(), separators=(",", ":")),
                ),
            )


__all__ = ["PostgresReportingLineDraftStore"]
