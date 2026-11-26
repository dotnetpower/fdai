"""Publish Core's latest entitlement notice into its singleton PostgreSQL row.

Core alone writes `licensing_entitlement_state`. The Operator role only reads it to
stamp authenticated responses for the Console watermark, so this adapter is the one
place a notice enters storage. A write never moves the observation time backward,
so a replica that resolved earlier cannot replace a newer notice.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import psycopg

from fdai.core.licensing.entitlement_notice import EntitlementNotice

Connect = Callable[..., Awaitable[Any]]

_UPSERT = """
    INSERT INTO licensing_entitlement_state (singleton, notice, observed_at)
    VALUES (TRUE, %s, %s)
    ON CONFLICT (singleton) DO UPDATE
    SET notice = EXCLUDED.notice, observed_at = EXCLUDED.observed_at
    WHERE licensing_entitlement_state.observed_at <= EXCLUDED.observed_at
"""


class PostgresEntitlementStateWriter:
    """Upsert one notice with its observation time under a monotonic predicate."""

    def __init__(
        self,
        *,
        dsn: str,
        statement_timeout_ms: int = 5_000,
        connect_timeout_s: int = 5,
        connect: Connect | None = None,
    ) -> None:
        if not dsn.strip():
            raise ValueError("entitlement state publication requires a state-store DSN")
        if statement_timeout_ms <= 0 or connect_timeout_s <= 0:
            raise ValueError("entitlement state timeouts must be positive")
        self._dsn = dsn
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._connect_timeout_s = int(connect_timeout_s)
        self._connect: Connect = connect or psycopg.AsyncConnection.connect

    async def publish(self, notice: EntitlementNotice, *, observed_at: datetime) -> None:
        """Record ``notice`` as observed at ``observed_at`` unless a newer one exists.

        Raises ``ValueError`` for a naive observation time and propagates storage
        errors, so the caller logs a missed publication instead of hiding it.
        """

        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("entitlement state requires a timezone-aware observation time")
        connection = await self._connect(self._dsn, connect_timeout=self._connect_timeout_s)
        async with connection, connection.transaction():
            await connection.execute(f"SET LOCAL statement_timeout = {self._statement_timeout_ms}")
            await connection.execute(_UPSERT, (EntitlementNotice(notice).value, observed_at))


__all__ = ["PostgresEntitlementStateWriter"]
