"""Unit tests for the PostgreSQL Jira ledger adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from fdai.delivery.persistence.postgres_idempotency import PostgresIdempotencyStoreConfig
from fdai.delivery.persistence.postgres_jira_ledger import PostgresJiraLedger


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self.records: dict[str, Mapping[str, Any]] = {}

    async def seen(self, key: str) -> Mapping[str, Any] | None:
        return self.records.get(key)

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        if key in self.records:
            return False
        self.records[key] = dict(result)
        return True

    async def replace_if(
        self,
        key: str,
        expected: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool:
        if self.records.get(key) != expected:
            return False
        self.records[key] = dict(result)
        return True

    async def remove_if(self, key: str, expected: Mapping[str, Any]) -> bool:
        if self.records.get(key) != expected:
            return False
        del self.records[key]
        return True

    async def insert_or_replace_if(
        self,
        key: str,
        expected: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool:
        existing = self.records.get(key)
        if existing is not None and existing not in (expected, result):
            return False
        self.records[key] = dict(result)
        return True


def _ledger() -> tuple[PostgresJiraLedger, FakeIdempotencyStore]:
    ledger = PostgresJiraLedger(config=PostgresIdempotencyStoreConfig(dsn="postgresql://example"))
    fake = FakeIdempotencyStore()
    ledger._store = fake  # type: ignore[assignment]  # noqa: SLF001 - adapter unit seam
    return ledger, fake


async def test_jira_ledger_round_trip_and_same_receipt_replay() -> None:
    ledger, _ = _ledger()

    await ledger.record("action-1", "OPS-42")
    await ledger.record("action-1", "OPS-42")

    assert await ledger.seen("action-1") == "OPS-42"


async def test_jira_ledger_rejects_receipt_conflict() -> None:
    ledger, _ = _ledger()
    await ledger.record("action-1", "OPS-42")

    with pytest.raises(RuntimeError, match="receipt conflict"):
        await ledger.record("action-1", "OPS-99")


async def test_jira_ledger_claim_complete_and_release() -> None:
    ledger, _ = _ledger()

    assert await ledger.claim("action-1") is True
    assert await ledger.claim("action-1") is False
    assert await ledger.seen("action-1") is None

    await ledger.record("action-1", "OPS-42")
    assert await ledger.seen("action-1") == "OPS-42"

    assert await ledger.claim("action-2") is True
    await ledger.release("action-2")
    assert await ledger.claim("action-2") is True


@pytest.mark.parametrize("release_first", [True, False])
async def test_jira_completion_wins_release_ordering(release_first: bool) -> None:
    ledger, _ = _ledger()
    assert await ledger.claim("action-1") is True

    if release_first:
        await ledger.release("action-1")
        await ledger.record("action-1", "OPS-42")
    else:
        await ledger.record("action-1", "OPS-42")
        await ledger.release("action-1")

    assert await ledger.seen("action-1") == "OPS-42"
