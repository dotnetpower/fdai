"""PostgreSQL-backed Jira issue idempotency ledger."""

from __future__ import annotations

from fdai.delivery.persistence.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)

_PREFIX = "jira-issue:"


class PostgresJiraLedger:
    """Adapt the shared idempotency table to Jira receipt references."""

    def __init__(self, *, config: PostgresIdempotencyStoreConfig) -> None:
        self._store = PostgresIdempotencyStore(config=config)

    async def seen(self, key: str) -> str | None:
        result = await self._store.seen(f"{_PREFIX}{key}")
        if result is None:
            return None
        if result.get("state") == "pending":
            return None
        receipt_ref = result.get("receipt_ref")
        if not isinstance(receipt_ref, str) or not receipt_ref:
            raise RuntimeError("Jira idempotency row has no receipt_ref")
        return receipt_ref

    async def claim(self, key: str) -> bool:
        return await self._store.record(
            f"{_PREFIX}{key}",
            {"state": "pending"},
        )

    async def release(self, key: str) -> None:
        await self._store.remove_if(
            f"{_PREFIX}{key}",
            {"state": "pending"},
        )

    async def record(self, key: str, receipt_ref: str) -> None:
        completed = {"state": "completed", "receipt_ref": receipt_ref}
        persisted = await self._store.insert_or_replace_if(
            f"{_PREFIX}{key}",
            {"state": "pending"},
            completed,
        )
        if persisted:
            return
        existing_ref = await self.seen(key)
        if existing_ref != receipt_ref:
            raise RuntimeError("Jira idempotency receipt conflict")


__all__ = ["PostgresJiraLedger"]
