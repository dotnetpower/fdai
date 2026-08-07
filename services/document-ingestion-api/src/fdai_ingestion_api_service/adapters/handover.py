"""PostgreSQL handover-draft projection for the ingestion API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts import DocumentNotFoundError
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class HandoverDraftArtifact:
    """Opaque service-owned projection of the worker-produced draft record."""

    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


class PostgresHandoverDraftReader:
    """Read the durable handover projection without importing worker code."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    (f"handover_draft:{upload_id}",),
                )
            ).fetchone()
        if row is None:
            raise DocumentNotFoundError("handover draft was not found")
        value: Any = row["value"]
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise RuntimeError("durable handover draft is malformed")
        return HandoverDraftArtifact(payload=dict(value))
