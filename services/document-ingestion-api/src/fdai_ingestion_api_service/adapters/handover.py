"""PostgreSQL handover-draft projection for the ingestion API."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    DocumentNotFoundError,
    HandoverDraftArtifact,
    handover_governance_idempotency_key,
)
from psycopg.rows import dict_row


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
        return HandoverDraftArtifact.model_validate(value)

    async def governance_delivered(self, artifact: HandoverDraftArtifact) -> bool:
        """Return true only for the exact published governance delivery receipt."""

        idempotency_key = handover_governance_idempotency_key(artifact)
        receipt_key = "stewardship_governance:" + idempotency_key.removeprefix(
            "stewardship-handover:"
        )
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    (receipt_key,),
                )
            ).fetchone()
        if row is None:
            return False
        value: Any = row["value"]
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict) or (
            value.get("upload_id") != str(artifact.upload_id)
            or value.get("document_id") != str(artifact.document_id)
            or value.get("version_id") != str(artifact.version_id)
            or value.get("idempotency_key") != idempotency_key
        ):
            raise RuntimeError("durable handover governance receipt is malformed")
        published = value.get("published")
        reason = value.get("reason")
        pr_ref = value.get("pr_ref")
        if published is False:
            return False
        if published is not True or reason is not None or not isinstance(pr_ref, str) or not pr_ref:
            raise RuntimeError("durable handover governance receipt is malformed")
        return True
