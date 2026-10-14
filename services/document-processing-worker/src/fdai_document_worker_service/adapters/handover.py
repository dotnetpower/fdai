"""Durable PostgreSQL storage for worker-produced handover drafts."""

from __future__ import annotations

import json
from uuid import UUID

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
                (
                    f"handover_draft:{artifact.upload_id}",
                    json.dumps(artifact.to_dict(), separators=(",", ":")),
                ),
            )

    async def reserve_model_calls(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_sha256: str,
    ) -> bool:
        """Reserve two calls once for the exact document version without restart refunds."""
        key = f"handover_draft:model-budget:{document_id}:{version_id}"
        reservation = {
            "schema_version": "1.0.0",
            "document_id": str(document_id),
            "version_id": str(version_id),
            "source_sha256": source_sha256,
            "reserved_calls": 2,
            "execution_authority": False,
        }
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (key) DO NOTHING RETURNING key",
                    (key, json.dumps(reservation, separators=(",", ":"))),
                )
            ).fetchone()
        return row is not None

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact | None:
        """Replay only an exact existing upload draft, never re-run its model."""
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    (f"handover_draft:{upload_id}",),
                )
            ).fetchone()
        if row is None:
            return None
        return HandoverDraftArtifact.model_validate(row[0])

    async def record_model_usage(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        stage: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_micros: int,
        pricing_sha256: str,
    ) -> None:
        """Retain measured author/reviewer cost even when interpretation is rejected."""
        if stage not in {"author", "reviewer"}:
            raise ValueError("handover model usage stage is invalid")
        key = f"handover_draft:model-budget:{document_id}:{version_id}"
        measured = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_micros": cost_micros,
            "pricing_sha256": pricing_sha256,
        }
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "UPDATE state_kv SET value = jsonb_set(value, ARRAY[%s], %s::jsonb) "
                    "WHERE key = %s AND value->>'reserved_calls' = '2' "
                    "AND NOT (value ? %s) RETURNING key",
                    (stage, json.dumps(measured, separators=(",", ":")), key, stage),
                )
            ).fetchone()
        if row is None:
            raise ValueError("handover measured usage cannot replace an existing call receipt")
