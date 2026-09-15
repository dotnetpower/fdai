"""Read insert-only Operator assignment receipts using the Core service identity."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres import PostgresStateStoreConfig


@dataclass(frozen=True, slots=True)
class PostgresAssignmentReceiptReader:
    """Resolve only the migrated immutable receipt table, never mutable ``state_kv``.

    A missing migration, wrong SQL role, or unavailable database fails closed. Legacy outbox
    rows are deliberately not a fallback and are not backfilled as authenticated receipts.
    """

    config: PostgresStateStoreConfig

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        """Read one exact bounded reference without copying it into diagnostic output."""
        if re.fullmatch(r"operator-proposal:iam:[a-f0-9]{64}", key) is None:
            raise ValueError("assignment receipt reference is invalid")
        async with await psycopg.AsyncConnection.connect(
            self.config.dsn,
            row_factory=dict_row,
            connect_timeout=self.config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.config.statement_timeout_ms),),
                )
                role = await (await connection.execute("SELECT current_user AS role")).fetchone()
                if role is None or role["role"] != "fdai_core":
                    raise PermissionError("assignment receipt reader requires the Core SQL role")
                cursor = await connection.execute(
                    "SELECT record FROM public.operator_assignment_receipt WHERE proposal_ref=%s",
                    (key,),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        record = row["record"]
        if not isinstance(record, dict):
            raise ValueError("assignment receipt is not an object")
        return record


__all__ = ["PostgresAssignmentReceiptReader"]
