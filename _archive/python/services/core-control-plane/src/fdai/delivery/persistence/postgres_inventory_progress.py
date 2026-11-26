"""PostgreSQL append-only store for identifier-free inventory progress records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg
from fdai_service_contracts import InventoryProgressRecord, InventoryProgressState
from psycopg.rows import dict_row

_INVENTORY_PROGRESS_GENESIS_DIGEST = "sha256:" + "0" * 64
_DEFAULT_TERMINAL_ATTEMPT_RETENTION = 16


@dataclass(frozen=True, slots=True)
class PostgresInventoryProgressStoreConfig:
    """Connection settings for bounded progress appends."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    terminal_attempt_retention: int = _DEFAULT_TERMINAL_ATTEMPT_RETENTION

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("inventory progress PostgreSQL DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("inventory progress PostgreSQL timeouts MUST be positive")
        if not 1 <= self.terminal_attempt_retention <= 1_000:
            raise ValueError("inventory progress terminal retention MUST be in [1, 1000]")


class PostgresInventoryProgressStore:
    """Append one exact hash chain under a transaction-scoped writer lock."""

    def __init__(self, *, config: PostgresInventoryProgressStoreConfig) -> None:
        self._config = config

    async def append(self, record: InventoryProgressRecord) -> bool:
        """Append a new sequence or verify an exact duplicate without repairing gaps."""

        async with await self._connect() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"inventory-progress:{record.run_id}:{record.attempt_id}",),
                )
                cursor = await connection.execute(
                    "SELECT sequence, record_digest FROM inventory_progress_event "
                    "WHERE run_id=%s AND attempt_id=%s "
                    "ORDER BY sequence DESC LIMIT 1",
                    (record.run_id, record.attempt_id),
                )
                latest = await cursor.fetchone()
                expected_sequence = 1 if latest is None else int(latest["sequence"]) + 1
                expected_previous = (
                    _INVENTORY_PROGRESS_GENESIS_DIGEST
                    if latest is None
                    else str(latest["record_digest"])
                )
                if record.sequence < expected_sequence:
                    return await self._verify_duplicate(connection, record)
                if record.sequence != expected_sequence:
                    raise ValueError("inventory progress sequence has a gap")
                if record.previous_digest != expected_previous:
                    raise ValueError("inventory progress previous digest does not match the chain")
                payload = record.model_dump(mode="json")
                await connection.execute(
                    "INSERT INTO inventory_progress_event "
                    "(run_id, attempt_id, sequence, previous_digest, record_digest, "
                    "stage, state, payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                    (
                        record.run_id,
                        record.attempt_id,
                        record.sequence,
                        record.previous_digest,
                        record.record_digest,
                        record.stage.value,
                        record.state.value,
                        json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    ),
                )
                if record.sequence == 1 or record.state is not InventoryProgressState.RUNNING:
                    prune_cursor = await connection.execute(
                        "SELECT fdai_prune_inventory_progress(%s) AS deleted_rows",
                        (self._config.terminal_attempt_retention,),
                    )
                    pruned = await prune_cursor.fetchone()
                    if pruned is None or int(pruned["deleted_rows"]) < 0:
                        raise RuntimeError("inventory progress retention returned invalid evidence")
                return True

    async def _verify_duplicate(
        self,
        connection: Any,
        record: InventoryProgressRecord,
    ) -> bool:
        cursor = await connection.execute(
            "SELECT payload FROM inventory_progress_event "
            "WHERE run_id=%s AND attempt_id=%s AND sequence=%s",
            (record.run_id, record.attempt_id, record.sequence),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("inventory progress sequence precedes a missing retained record")
        try:
            retained = InventoryProgressRecord.model_validate(row["payload"])
        except (TypeError, ValueError) as exc:
            raise ValueError("retained inventory progress record is invalid") from exc
        if retained != record:
            raise ValueError("inventory progress replay conflicts with retained content")
        return False

    async def _connect(self) -> Any:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )


__all__ = [
    "PostgresInventoryProgressStore",
    "PostgresInventoryProgressStoreConfig",
]
