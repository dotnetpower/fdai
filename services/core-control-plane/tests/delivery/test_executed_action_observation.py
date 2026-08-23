"""Heimdall terminal ActionRun observation handler tests."""

from __future__ import annotations

import pytest
from fdai.delivery.executed_action_observation import (
    HeimdallExecutedActionObservationHandler,
)
from fdai.delivery.reconciliation_artifacts import StateStoreExecutedActionArtifactStore
from fdai.delivery.reconciliation_observations import StateStoreExecutedActionObservationStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.delivery.test_reconciliation_observations import _Verifier
from tests.delivery.test_reconciliation_request import _inputs


class _Collector:
    def __init__(self, observation) -> None:
        self.observation = observation
        self.calls: list[dict[str, object]] = []

    async def collect(self, **kwargs):
        self.calls.append(kwargs)
        return self.observation


def _payload(action, correlation_id: str, *, state: str = "succeeded") -> dict[str, object]:
    return {
        "producer_principal": "Thor",
        "correlation_id": correlation_id,
        "action_idempotency_key": action.idempotency_key,
        "action_type": action.action_type,
        "resource_id": action.target_resource_ref,
        "state": state,
        "terminal_at": action.created_at.isoformat(),
        "execution_receipt_ref": "receipt:provider:one",
    }


async def _handler():
    artifacts, action, observation = _inputs()
    correlation_id = str(action.action_id)
    store = InMemoryStateStore()
    artifact_store = StateStoreExecutedActionArtifactStore(store=store)
    await artifact_store.store(
        action=action,
        plan=artifacts.plan,
        action_type=artifacts.action_type,
        active_release=artifacts.active_release,
        correlation_id=correlation_id,
    )
    collector = _Collector(observation)
    observation_store = StateStoreExecutedActionObservationStore(
        store=store,
        verifier=_Verifier(),
    )
    handler = HeimdallExecutedActionObservationHandler(
        artifacts=artifact_store,
        collector=collector,
        observations=observation_store,
    )
    return handler, collector, observation_store, artifacts, action, correlation_id


async def test_terminal_action_run_collects_and_seals_exact_observation() -> None:
    handler, collector, observations, artifacts, action, correlation_id = await _handler()

    assert await handler.handle(_payload(action, correlation_id)) is True
    loaded = await observations.observe(
        action=action,
        artifacts=artifacts,
        execution_outcome="succeeded",
        execution_receipt_ref="receipt:provider:one",
        correlation_id=correlation_id,
    )

    assert loaded is not None
    assert len(collector.calls) == 1


async def test_nonterminal_action_run_does_not_call_collector() -> None:
    handler, collector, _, _, action, correlation_id = await _handler()

    assert await handler.handle(_payload(action, correlation_id, state="executing")) is False
    assert collector.calls == []


async def test_forged_action_run_producer_is_rejected() -> None:
    handler, collector, _, _, action, correlation_id = await _handler()
    payload = _payload(action, correlation_id)
    payload["producer_principal"] = "NotThor"

    with pytest.raises(ValueError, match="MUST be produced by Thor"):
        await handler.handle(payload)
    assert collector.calls == []


async def test_substituted_action_run_target_is_rejected() -> None:
    handler, collector, _, _, action, correlation_id = await _handler()
    payload = _payload(action, correlation_id)
    payload["resource_id"] = "substituted-target"

    with pytest.raises(ValueError, match="changed exact Action identity"):
        await handler.handle(payload)
    assert collector.calls == []


async def test_collector_evidence_for_another_correlation_is_rejected() -> None:
    handler, collector, _, _, action, correlation_id = await _handler()
    collector.observation = collector.observation.__class__(
        evidence=collector.observation.evidence.model_copy(
            update={"correlation_id": "another-correlation"}
        ),
        observation_context=collector.observation.observation_context,
        deadline=collector.observation.deadline,
        evaluated_at=collector.observation.evaluated_at,
    )

    with pytest.raises(ValueError, match="does not match exact artifacts"):
        await handler.handle(_payload(action, correlation_id))
