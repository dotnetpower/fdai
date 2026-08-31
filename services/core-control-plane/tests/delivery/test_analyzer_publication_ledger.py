"""Durable analyzer publication claim and acknowledgement tests."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.analyzer_tick import AnalyzerPublicationClaimStatus
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.shared.providers.event_bus import PublishReceipt


class ConditionalStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    async def seen(self, key: str) -> Mapping[str, Any] | None:
        value = self.values.get(key)
        return deepcopy(value) if value is not None else None

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(result)
        return True

    async def remove_if(self, key: str, expected: Mapping[str, Any]) -> bool:
        if self.values.get(key) != expected:
            return False
        del self.values[key]
        return True

    async def insert_or_replace_if(
        self,
        key: str,
        expected: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool:
        current = self.values.get(key)
        if current is None:
            self.values[key] = dict(result)
            return True
        if current != expected and current != result:
            return False
        self.values[key] = dict(result)
        return True


def _ledger(store: ConditionalStore | None = None) -> PostgresAnalyzerPublicationLedger:
    return PostgresAnalyzerPublicationLedger(store=store or ConditionalStore())


async def test_first_claim_wins_and_completion_retains_broker_receipt() -> None:
    store = ConditionalStore()
    first_process = _ledger(store)
    restarted_process = _ledger(store)

    first_claim = await first_process.claim("analyzer:resource:signal:1")
    duplicate_claim = await restarted_process.claim("analyzer:resource:signal:1")
    assert first_claim.status is AnalyzerPublicationClaimStatus.NEW
    assert duplicate_claim.status is AnalyzerPublicationClaimStatus.IN_PROGRESS
    await first_process.complete(
        "analyzer:resource:signal:1",
        first_claim,
        PublishReceipt(topic="fdai.change.events", partition=2, offset=17),
    )
    completed_claim = await restarted_process.claim("analyzer:resource:signal:1")

    assert completed_claim.status is AnalyzerPublicationClaimStatus.COMPLETED
    assert completed_claim.receipt == PublishReceipt(
        topic="fdai.change.events", partition=2, offset=17
    )
    assert store.values["analyzer-publication:analyzer:resource:signal:1"] == {
        "state": "completed",
        "topic": "fdai.change.events",
        "partition": 2,
        "offset": 17,
    }


async def test_failed_publication_release_allows_one_retry() -> None:
    ledger = _ledger()

    first = await ledger.claim("key")
    assert first.status is AnalyzerPublicationClaimStatus.NEW
    await ledger.release("key", first)
    assert (await ledger.claim("key")).status is AnalyzerPublicationClaimStatus.NEW


async def test_stale_pending_claim_is_reclaimed_with_a_new_token() -> None:
    store = ConditionalStore()
    store.values["analyzer-publication:key"] = {
        "state": "pending",
        "token": "old-token",
        "claimed_at": (datetime.now(tz=UTC) - timedelta(seconds=2)).isoformat(),
    }
    ledger = PostgresAnalyzerPublicationLedger(store=store, lease_seconds=1)

    reclaimed = await ledger.claim("key")

    assert reclaimed.status is AnalyzerPublicationClaimStatus.NEW
    assert reclaimed.token != "old-token"


async def test_completion_refuses_a_conflicting_existing_receipt() -> None:
    store = ConditionalStore()
    store.values["analyzer-publication:key"] = {
        "state": "completed",
        "topic": "other",
        "partition": 1,
        "offset": 4,
    }
    ledger = _ledger(store)
    new_claim_store = ConditionalStore()
    new_ledger = _ledger(new_claim_store)
    new_claim = await new_ledger.claim("key")

    with pytest.raises(RuntimeError, match="receipt conflict"):
        await ledger.complete(
            "key",
            new_claim,
            PublishReceipt(topic="fdai.change.events", partition=0, offset=1),
        )


def test_exactly_one_store_binding_is_required() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        PostgresAnalyzerPublicationLedger()
