"""Durability and atomicity tests for the StateStore reconciliation ledger."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    ReconciliationAggregateLimitError,
    ReconciliationAttemptLimitError,
    ReconciliationConflictError,
    ReconciliationLedgerCorruptionError,
    ReconciliationPublicationStatus,
    StateStoreReconciliationLedger,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.ontology_platform.test_reconciliation import (
    CREATED_AT,
    _authenticated_context,
    _coordinate,
    _fixture,
    _request,
)


async def test_terminal_outcome_and_outbox_survive_ledger_restart_atomically() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    first = await _coordinate(
        EffectReconciliationCoordinator(ledger=StateStoreReconciliationLedger(store=store)),
        request,
        release=release,
    )
    replay = await _coordinate(
        EffectReconciliationCoordinator(ledger=StateStoreReconciliationLedger(store=store)),
        request,
        release=release,
    )

    record = await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}")
    assert replay == first
    assert record is not None
    assert record["revision"] == 1
    assert record["terminal_outcome"] == first.model_dump(mode="json")
    assert record["outbox"] == {
        first.recommendation.idempotency_key: first.recommendation.model_dump(mode="json")
    }
    assert len(tuple(store.audit_entries)) == 1
    assert await store.verify_chain()


async def test_concurrent_terminal_replay_commits_one_aggregate_revision() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()

    outcomes = await asyncio.gather(
        *(
            _coordinate(
                EffectReconciliationCoordinator(ledger=StateStoreReconciliationLedger(store=store)),
                request,
                release=release,
            )
            for _ in range(32)
        )
    )

    record = await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}")
    assert all(outcome == outcomes[0] for outcome in outcomes)
    assert record is not None
    assert record["revision"] == 1
    assert len(record["attempts"]) == 1
    assert len(record["outbox"]) == 1
    assert len(tuple(store.audit_entries)) == 1


async def test_same_request_digest_preserves_canonical_durable_outcome() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    ledger = StateStoreReconciliationLedger(store=store)
    canonical = await _coordinate(
        EffectReconciliationCoordinator(ledger=ledger),
        request,
        release=release,
    )
    alternate_derivation = canonical.model_copy(update={"receipt_digest": "sha256:" + "f" * 64})

    replay = await ledger.commit_terminal(alternate_derivation)

    assert replay == canonical
    assert len(tuple(store.audit_entries)) == 1


async def test_unscorable_attempt_transitions_to_terminal_and_survives_restart() -> None:
    release, target, plan, action_type = _fixture()
    first_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    retry_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        observed_at=CREATED_AT + timedelta(minutes=1, seconds=1),
    )
    store = InMemoryStateStore()
    first = await EffectReconciliationCoordinator(
        ledger=StateStoreReconciliationLedger(store=store)
    ).coordinate(
        first_request,
        observation_context=_authenticated_context(first_request).model_copy(
            update={"observer_credential_lineage": "credential:thor-executor:1"}
        ),
        active_release=release,
    )
    terminal = await _coordinate(
        EffectReconciliationCoordinator(ledger=StateStoreReconciliationLedger(store=store)),
        retry_request,
        release=release,
    )
    replay = await _coordinate(
        EffectReconciliationCoordinator(ledger=StateStoreReconciliationLedger(store=store)),
        retry_request,
        release=release,
    )

    record = await store.read_state(f"ontology:reconciliation:{first_request.reconciliation_id}")
    assert first.terminal is False
    assert terminal.terminal is True
    assert replay == terminal
    assert record is not None
    assert record["revision"] == 2
    assert set(record["attempts"]) == {
        first.observation_attempt_id,
        terminal.observation_attempt_id,
    }
    assert record["terminal_outcome"] == terminal.model_dump(mode="json")
    assert len(record["outbox"]) == 1
    assert len(tuple(store.audit_entries)) == 2
    assert await store.verify_chain()


async def test_terminal_identity_conflict_and_corrupt_state_fail_closed() -> None:
    release, target, plan, action_type = _fixture()
    first_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    conflicting_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        observed_at=CREATED_AT + timedelta(minutes=1, seconds=1),
    )
    store = InMemoryStateStore()
    coordinator = EffectReconciliationCoordinator(
        ledger=StateStoreReconciliationLedger(store=store)
    )
    await _coordinate(coordinator, first_request, release=release)

    with pytest.raises(ReconciliationConflictError, match="terminal identity"):
        await _coordinate(coordinator, conflicting_request, release=release)

    key = f"ontology:reconciliation:{first_request.reconciliation_id}"
    record = await store.read_state(key)
    assert record is not None
    await store.write_state(key, {**record, "outbox": {}})

    with pytest.raises(ReconciliationLedgerCorruptionError):
        await _coordinate(
            EffectReconciliationCoordinator(ledger=StateStoreReconciliationLedger(store=store)),
            first_request,
            release=release,
        )


async def test_attempt_limit_reserves_capacity_for_terminal_closure() -> None:
    release, target, plan, action_type = _fixture()
    store = InMemoryStateStore()
    coordinator = EffectReconciliationCoordinator(
        ledger=StateStoreReconciliationLedger(store=store)
    )

    for offset in range(7):
        request = _request(
            release=release,
            target=target,
            plan=plan,
            action_type=action_type,
            observed_at=CREATED_AT + timedelta(minutes=1, microseconds=offset),
        )
        outcome = await coordinator.coordinate(
            request,
            observation_context=_authenticated_context(request).model_copy(
                update={"observer_credential_lineage": "credential:thor-executor:1"}
            ),
            active_release=release,
        )
        assert outcome.terminal is False

    rejected = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        observed_at=CREATED_AT + timedelta(minutes=1, microseconds=7),
    )
    with pytest.raises(ReconciliationAttemptLimitError):
        await coordinator.coordinate(
            rejected,
            observation_context=_authenticated_context(rejected).model_copy(
                update={"observer_credential_lineage": "credential:thor-executor:1"}
            ),
            active_release=release,
        )

    terminal_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        observed_at=CREATED_AT + timedelta(minutes=1, microseconds=8),
    )
    terminal = await _coordinate(coordinator, terminal_request, release=release)

    record = await store.read_state(f"ontology:reconciliation:{terminal_request.reconciliation_id}")
    assert terminal.terminal is True
    assert record is not None
    assert len(record["attempts"]) == 8


async def test_aggregate_byte_limit_fails_before_state_or_audit_write() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    ledger = StateStoreReconciliationLedger(store=store)
    ledger._MAX_AGGREGATE_BYTES = 1

    with pytest.raises(ReconciliationAggregateLimitError, match="canonical byte limit"):
        await _coordinate(
            EffectReconciliationCoordinator(ledger=ledger),
            request,
            release=release,
        )

    assert await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}") is None
    assert tuple(store.audit_entries) == ()


async def test_durable_outbox_claim_and_broker_completion_survive_restart() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    ledger = StateStoreReconciliationLedger(store=store)
    outcome = await _coordinate(
        EffectReconciliationCoordinator(ledger=ledger),
        request,
        release=release,
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)

    claimed = await StateStoreReconciliationLedger(store=store).claim_publications(
        now=now,
        limit=10,
        lease_until=now + timedelta(minutes=1),
    )
    assert len(claimed) == 1
    assert claimed[0].status is ReconciliationPublicationStatus.IN_PROGRESS
    assert claimed[0].recommendation == outcome.recommendation

    restarted = StateStoreReconciliationLedger(store=store)
    await restarted.complete_publication(
        request.reconciliation_id,
        outcome.recommendation.idempotency_key,
        published_at=now + timedelta(seconds=1),
        topic="command.reconciliation-decision",
        partition=2,
        offset=17,
    )

    assert (
        await restarted.claim_publications(
            now=now + timedelta(minutes=2),
            limit=10,
            lease_until=now + timedelta(minutes=3),
        )
        == ()
    )
    record = await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}")
    assert record is not None
    publication = next(iter(record["publication_state"].values()))
    assert publication["status"] == "published"
    assert publication["topic"] == "command.reconciliation-decision"
    assert publication["offset"] == 17


async def test_durable_outbox_lease_prevents_concurrent_claim_and_replays_after_expiry() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    await _coordinate(
        EffectReconciliationCoordinator(ledger=StateStoreReconciliationLedger(store=store)),
        request,
        release=release,
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)

    claims = await asyncio.gather(
        *(
            StateStoreReconciliationLedger(store=store).claim_publications(
                now=now,
                limit=1,
                lease_until=now + timedelta(seconds=30),
            )
            for _ in range(16)
        )
    )
    assert sum(bool(item) for item in claims) == 1

    replay = await StateStoreReconciliationLedger(store=store).claim_publications(
        now=now + timedelta(seconds=31),
        limit=1,
        lease_until=now + timedelta(seconds=61),
    )
    assert len(replay) == 1
    assert replay[0].attempts == 2


async def test_durable_outbox_release_retries_and_conflicting_completion_fails_closed() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    ledger = StateStoreReconciliationLedger(store=store)
    outcome = await _coordinate(
        EffectReconciliationCoordinator(ledger=ledger),
        request,
        release=release,
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)
    await ledger.claim_publications(
        now=now,
        limit=1,
        lease_until=now + timedelta(seconds=30),
    )
    await ledger.release_publication(
        request.reconciliation_id,
        outcome.recommendation.idempotency_key,
        available_at=now + timedelta(seconds=10),
        error="TimeoutError",
    )
    assert (
        await ledger.claim_publications(
            now=now + timedelta(seconds=9),
            limit=1,
            lease_until=now + timedelta(seconds=20),
        )
        == ()
    )
    assert await ledger.claim_publications(
        now=now + timedelta(seconds=10),
        limit=1,
        lease_until=now + timedelta(seconds=20),
    )
    await ledger.complete_publication(
        request.reconciliation_id,
        outcome.recommendation.idempotency_key,
        published_at=now + timedelta(seconds=11),
        topic="command.reconciliation-decision",
        partition=0,
        offset=9,
    )

    with pytest.raises(ReconciliationConflictError, match="conflicting broker evidence"):
        await ledger.complete_publication(
            request.reconciliation_id,
            outcome.recommendation.idempotency_key,
            published_at=now + timedelta(seconds=12),
            topic="command.reconciliation-decision",
            partition=0,
            offset=10,
        )
