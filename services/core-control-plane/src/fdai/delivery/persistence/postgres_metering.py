"""Durable Postgres storage for measured LLM invocations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
from fdai.core.metering.usage import TokenUsage


@dataclass(frozen=True, slots=True)
class PostgresMeteringStoreConfig:
    """Connection settings for :class:`PostgresMeteringStore`."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresMeteringStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")


class PostgresMeteringStore:
    """Append and read LLM invocation facts from ``llm_invocation``."""

    def __init__(self, *, config: PostgresMeteringStoreConfig) -> None:
        self._config: Final[PostgresMeteringStoreConfig] = config

    async def record(self, invocation: LlmInvocation) -> None:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                await connection.execute(
                    """
                    INSERT INTO llm_invocation (
                        occurred_at, correlation_id, capability_id, model_key,
                        tier, mode, usage_scope, prompt_tokens, completion_tokens, cost, currency
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT DO NOTHING
                    """,
                    (
                        invocation.occurred_at,
                        invocation.correlation_id,
                        invocation.capability_id,
                        invocation.model_key,
                        invocation.tier,
                        invocation.mode.value,
                        invocation.usage_scope.value,
                        invocation.usage.prompt_tokens,
                        invocation.usage.completion_tokens,
                        invocation.cost,
                        invocation.currency,
                    ),
                )

    async def invocations(self) -> tuple[LlmInvocation, ...]:
        async with await self._connect(row_factory=True) as connection:
            await self._set_statement_timeout(connection)
            cursor = await connection.execute(
                """
                SELECT occurred_at, correlation_id, capability_id, model_key,
                      tier, mode, usage_scope, prompt_tokens, completion_tokens, cost, currency
                  FROM llm_invocation
                 ORDER BY occurred_at, invocation_id
                """
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_invocation(row) for row in rows)

    async def _connect(self, *, row_factory: bool = False) -> psycopg.AsyncConnection[Any]:
        kwargs: dict[str, Any] = {"connect_timeout": self._config.connect_timeout_s}
        if row_factory:
            kwargs["row_factory"] = dict_row
        return await psycopg.AsyncConnection.connect(self._config.dsn, **kwargs)

    async def _set_statement_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout_ms = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout_ms}")


def _row_to_invocation(row: dict[str, Any]) -> LlmInvocation:
    raw_cost = row["cost"]
    return LlmInvocation(
        occurred_at=row["occurred_at"],
        correlation_id=str(row["correlation_id"]),
        capability_id=str(row["capability_id"]),
        model_key=str(row["model_key"]),
        tier=str(row["tier"]),
        mode=InvocationMode(str(row["mode"])),
        usage=TokenUsage(
            prompt_tokens=int(row["prompt_tokens"]),
            completion_tokens=int(row["completion_tokens"]),
        ),
        usage_scope=InvocationScope(str(row["usage_scope"])),
        cost=Decimal(str(raw_cost)) if raw_cost is not None else None,
        currency=str(row["currency"]) if row["currency"] is not None else None,
    )


__all__ = ["PostgresMeteringStore", "PostgresMeteringStoreConfig"]
