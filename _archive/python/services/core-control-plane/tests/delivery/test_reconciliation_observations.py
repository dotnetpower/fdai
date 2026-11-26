"""Durable independent executed-Action observation tests."""

from __future__ import annotations

import pytest
from fdai.delivery.reconciliation_observations import (
    ExecutedActionObservationConflictError,
    StateStoreExecutedActionObservationStore,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.delivery.test_reconciliation_request import _inputs


class _Verifier:
    async def verify(self, *, evidence, claimed_context):
        assert claimed_context.verification_receipt.observation_digest == evidence.content_digest()
        return claimed_context


async def test_heimdall_observation_round_trips_with_exact_execution() -> None:
    artifacts, action, observation = _inputs()
    source = StateStoreExecutedActionObservationStore(
        store=InMemoryStateStore(),
        verifier=_Verifier(),
    )
    correlation_id = str(action.action_id)

    await source.record(
        producer_principal="Heimdall",
        action=action,
        artifacts=artifacts,
        execution_outcome="dispatched",
        execution_receipt_ref="receipt:executor:one",
        correlation_id=correlation_id,
        observation=observation,
    )
    loaded = await source.observe(
        action=action,
        artifacts=artifacts,
        execution_outcome="dispatched",
        execution_receipt_ref="receipt:executor:one",
        correlation_id=correlation_id,
    )

    assert loaded == observation


async def test_missing_observation_remains_unavailable() -> None:
    artifacts, action, _ = _inputs()
    source = StateStoreExecutedActionObservationStore(
        store=InMemoryStateStore(),
        verifier=_Verifier(),
    )

    assert (
        await source.observe(
            action=action,
            artifacts=artifacts,
            execution_outcome="dispatched",
            execution_receipt_ref="receipt:executor:one",
            correlation_id=str(action.action_id),
        )
        is None
    )


async def test_conflicting_observation_for_exact_plan_is_rejected() -> None:
    artifacts, action, observation = _inputs()
    source = StateStoreExecutedActionObservationStore(
        store=InMemoryStateStore(),
        verifier=_Verifier(),
    )
    arguments = {
        "producer_principal": "Heimdall",
        "action": action,
        "artifacts": artifacts,
        "execution_outcome": "dispatched",
        "execution_receipt_ref": "receipt:executor:one",
        "correlation_id": str(action.action_id),
        "observation": observation,
    }
    await source.record(**arguments)

    with pytest.raises(ExecutedActionObservationConflictError):
        await source.record(**{**arguments, "execution_outcome": "failed"})


async def test_observation_rejects_different_execution_context() -> None:
    artifacts, action, observation = _inputs()
    source = StateStoreExecutedActionObservationStore(
        store=InMemoryStateStore(),
        verifier=_Verifier(),
    )
    await source.record(
        producer_principal="Heimdall",
        action=action,
        artifacts=artifacts,
        execution_outcome="dispatched",
        execution_receipt_ref="receipt:executor:one",
        correlation_id=str(action.action_id),
        observation=observation,
    )

    with pytest.raises(ValueError, match="does not match exact execution"):
        await source.observe(
            action=action,
            artifacts=artifacts,
            execution_outcome="failed",
            execution_receipt_ref="receipt:executor:one",
            correlation_id=str(action.action_id),
        )
