"""Durable analyzer publication claim, send-intent, and acknowledgement tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.analyzer_tick import AnalyzerPublicationClaimStatus
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.shared.providers.event_bus import PublishReceipt

from tests.delivery.publication_store import ConditionalStore


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


async def test_send_intent_is_durable_before_the_record_leaves_the_process() -> None:
    store = ConditionalStore()
    ledger = _ledger(store)

    claim = await ledger.claim("key")
    sending = await ledger.mark_sending("key", claim)

    assert sending.status is AnalyzerPublicationClaimStatus.SENDING
    assert store.values["analyzer-publication:key"]["state"] == "sending"
    assert store.values["analyzer-publication:key"]["token"] == claim.token


async def test_a_crash_after_a_send_attempt_resolves_to_uncertain_not_a_new_claim() -> None:
    store = ConditionalStore()
    crashed = PostgresAnalyzerPublicationLedger(store=store, lease_seconds=1)
    claim = await crashed.claim("key")
    await crashed.mark_sending("key", claim)
    store.values["analyzer-publication:key"]["claimed_at"] = (
        datetime.now(tz=UTC) - timedelta(seconds=5)
    ).isoformat()

    restarted = PostgresAnalyzerPublicationLedger(store=store, lease_seconds=1)
    resumed = await restarted.claim("key")

    assert resumed.status is AnalyzerPublicationClaimStatus.UNCERTAIN
    assert store.values["analyzer-publication:key"]["state"] == "uncertain"
    assert store.values["analyzer-publication:key"]["reason"] == "lease_expired_after_send_attempt"


async def test_an_uncertain_key_stays_uncertain_until_it_is_resolved() -> None:
    store = ConditionalStore()
    ledger = PostgresAnalyzerPublicationLedger(store=store, lease_seconds=1)
    claim = await ledger.claim("key")
    sending = await ledger.mark_sending("key", claim)
    await ledger.mark_uncertain("key", sending, reason="TimeoutError:broker ack unknown")

    for _ in range(3):
        resumed = await ledger.claim("key")
        assert resumed.status is AnalyzerPublicationClaimStatus.UNCERTAIN

    assert store.values["analyzer-publication:key"]["reason"] == "TimeoutError:broker ack unknown"


async def test_reconciliation_may_complete_or_release_an_uncertain_key() -> None:
    store = ConditionalStore()
    ledger = _ledger(store)
    claim = await ledger.claim("completed-key")
    sending = await ledger.mark_sending("completed-key", claim)
    uncertain = await ledger.mark_uncertain("completed-key", sending, reason="unknown")
    await ledger.complete(
        "completed-key",
        uncertain,
        PublishReceipt(topic="fdai.change.events", partition=0, offset=9),
    )

    assert (await ledger.claim("completed-key")).status is AnalyzerPublicationClaimStatus.COMPLETED

    released = await ledger.claim("released-key")
    released_sending = await ledger.mark_sending("released-key", released)
    released_uncertain = await ledger.mark_uncertain(
        "released-key", released_sending, reason="unknown"
    )
    await ledger.release("released-key", released_uncertain)

    assert (await ledger.claim("released-key")).status is AnalyzerPublicationClaimStatus.NEW


async def test_a_send_intent_is_released_only_with_a_provably_unsent_attestation() -> None:
    store = ConditionalStore()
    ledger = _ledger(store)
    claim = await ledger.claim("key")
    sending = await ledger.mark_sending("key", claim)

    with pytest.raises(ValueError, match="rejects claim state"):
        await ledger.release("key", sending)
    assert store.values["analyzer-publication:key"]["state"] == "sending"

    await ledger.release("key", sending, provably_unsent=True)

    assert store.values == {}
    assert (await ledger.claim("key")).status is AnalyzerPublicationClaimStatus.NEW


async def test_a_transition_requires_the_exact_observed_record() -> None:
    store = ConditionalStore()
    ledger = _ledger(store)
    claim = await ledger.claim("key")
    store.values["analyzer-publication:key"]["token"] = "another-owner"

    with pytest.raises(RuntimeError, match="changed before send"):
        await ledger.mark_sending("key", claim)
