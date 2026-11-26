"""PostgreSQL audit publisher for automation blueprint review events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class PostgresAutomationBlueprintAuditConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresAutomationBlueprintAudit:
    """Append audit records to the shared state store without execution authority."""

    def __init__(self, config: PostgresAutomationBlueprintAuditConfig) -> None:
        if not config.dsn.strip():
            raise ValueError("automation blueprint audit dsn MUST be non-empty")
        self._config = config

    async def append(self, event: Mapping[str, Any]) -> None:
        payload = {
            "kind": "automation_blueprint.audit",
            "recorded_at": datetime.now(UTC).isoformat(),
            "event": dict(event),
            "execution_authority": False,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        key = f"automation-blueprint:audit:{digest}"
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO NOTHING",
                (key, json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)),
            )


__all__ = ["PostgresAutomationBlueprintAudit", "PostgresAutomationBlueprintAuditConfig"]
