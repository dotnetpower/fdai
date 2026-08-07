"""Durable PostgreSQL storage for worker-produced handover drafts."""

from __future__ import annotations

import psycopg
from fdai_service_contracts import HandoverDraftArtifact


class PostgresHandoverDraftStore:
    """Upsert a review-only draft into the shared state projection."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        if not dsn:
            raise ValueError("handover draft PostgreSQL DSN MUST NOT be empty")
        if connect_timeout_s < 1:
            raise ValueError("handover draft connect timeout MUST be positive")
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def put(self, artifact: HandoverDraftArtifact) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (f"handover_draft:{artifact.upload_id}", artifact.model_dump_json()),
            )
