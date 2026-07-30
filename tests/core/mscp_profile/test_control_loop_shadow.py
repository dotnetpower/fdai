"""Control-loop wiring tests for MSCP shadow effect observation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from fdai.core.control_loop import ControlLoop
from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.mscp_profile import ExpectedEffect, ObservedEffect
from fdai.shared.contracts.models import Action, Rule
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 21, tzinfo=UTC)


def _action() -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": "ops.scale-out",
            "target_resource_ref": "resource:example/rg/vm-a",
            "operation": "scale",
            "params": {},
            "stop_condition": "provider_api_error_streak",
            "stop_conditions": [{"kind": "provider_api_error_streak", "count": 3}],
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 5},
            "mode": "shadow",
            "citing_rules": ["example.rule.x"],
            "created_at": "2026-07-21T00:00:00Z",
        }
    )


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "example.rule.x",
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "config_drift",
            "resource_type": "compute.vm",
            "check_logic": {"kind": "rego", "reference": "policies/example/x.rego"},
            "remediation": {"template_ref": "remediations/example-x"},
            "remediates": "ops.scale-out",
            "provenance": {
                "source_url": "https://example.com/x",
                "resolved_ref": "0" * 40,
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-21T00:00:00Z",
            },
        }
    )


def _expected() -> ExpectedEffect:
    return ExpectedEffect(
        prediction_id="prediction-1",
        target_ref=_action().target_resource_ref,
        metric="delivery_receipt_count",
        acceptable_min=1.0,
        acceptable_max=1.0,
        predicted_at=_NOW,
        observation_deadline=_NOW + timedelta(minutes=5),
    )


def _result() -> ExecutionResult:
    return ExecutionResult(
        action_id=str(_action().action_id),
        outcome=ExecutorOutcome.PUBLISHED,
    )


def _loop(
    *,
    executor: Any,
    audit_store: Any,
    expected_effect_provider: Any = None,
    effect_observer: Any = None,
    response_outcome_sink: Any = None,
) -> ControlLoop:
    return ControlLoop(
        event_ingest=MagicMock(),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=MagicMock(),
        executor=executor,
        audit_store=audit_store,
        rules_by_id={_rule().id: _rule()},
        mscp_expected_effect_provider=expected_effect_provider,
        mscp_effect_observer=effect_observer,
        response_outcome_sink=response_outcome_sink,
    )


def _audit_payloads(store: InMemoryStateStore) -> tuple[dict[str, Any], ...]:
    return tuple(dict(record["entry"]) for record in store.audit_entries)


def _entry(entries: tuple[dict[str, Any], ...], action_kind: str) -> dict[str, Any]:
    return next(item for item in entries if item["action_kind"] == action_kind)


def test_partial_binding_fails_fast() -> None:
    async def predict(_action: Action) -> ExpectedEffect:
        return _expected()

    with pytest.raises(ValueError, match="MUST be bound together"):
        _loop(
            executor=MagicMock(),
            audit_store=InMemoryStateStore(),
            expected_effect_provider=predict,
        )


async def test_unbound_profile_is_a_complete_dispatch_noop() -> None:
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=_result())
    audit = InMemoryStateStore()
    loop = _loop(executor=executor, audit_store=audit)

    result = await loop._dispatch_action(action=_action(), rule=_rule())

    assert result is executor.execute.return_value
    assert _audit_payloads(audit) == ()


async def test_bound_profile_predicts_before_dispatch_and_observes_after() -> None:
    order: list[str] = []

    async def predict(_action: Action) -> ExpectedEffect:
        order.append("predict")
        return _expected()

    async def execute(*, action: Action, rule: Rule) -> ExecutionResult:  # noqa: ARG001
        order.append("execute")
        return _result()

    async def observe(_action: Action, expected: ExpectedEffect) -> ObservedEffect:
        order.append("observe")
        return ObservedEffect(
            prediction_id=expected.prediction_id,
            target_ref=expected.target_ref,
            metric=expected.metric,
            value=1.0,
            observed_at=_NOW + timedelta(minutes=1),
        )

    async def relay(outcome: Any) -> None:
        order.append("relay")
        assert outcome.label.value == "verified"

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=execute)
    audit = InMemoryStateStore()
    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observe,
        response_outcome_sink=relay,
    )

    result = await loop._dispatch_action(action=_action(), rule=_rule())
    entries = _audit_payloads(audit)

    assert result.outcome is ExecutorOutcome.PUBLISHED
    assert order == ["predict", "execute", "observe", "relay"]
    assert len(entries) == 2
    effect_entry = _entry(entries, "effect_verification.shadow")
    assert effect_entry["verification_status"] == "verified"
    assert effect_entry["safety_profile"] == "mscp-operational-v1"
    assert effect_entry["mode"] == "shadow"
    response_entry = _entry(entries, "measurement.action_outcome.v1")
    assert response_entry["label"] == "verified"
    assert response_entry["scorable"] is True
    assert response_entry["verification_passed"] is True
    assert response_entry["decision"] == "auto"
    assert "target_resource_ref" not in response_entry


async def test_mismatch_is_audited_without_changing_execution_result() -> None:
    async def predict(_action: Action) -> ExpectedEffect:
        return _expected()

    async def observe(_action: Action, expected: ExpectedEffect) -> ObservedEffect:
        return ObservedEffect(
            prediction_id=expected.prediction_id,
            target_ref=expected.target_ref,
            metric=expected.metric,
            value=0.0,
            observed_at=_NOW + timedelta(minutes=1),
        )

    expected_result = _result()
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=expected_result)
    audit = InMemoryStateStore()
    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observe,
    )

    result = await loop._dispatch_action(action=_action(), rule=_rule())
    entry = _entry(_audit_payloads(audit), "measurement.action_outcome.v1")

    assert result is expected_result
    assert entry["verification_status"] == "mismatch"
    assert entry["verification_reason"] == "value_outside_acceptable_range"


@pytest.mark.parametrize("failure_side", ["prediction", "observation"])
async def test_provider_failure_holds_without_breaking_dispatch(failure_side: str) -> None:
    async def predict(_action: Action) -> ExpectedEffect:
        if failure_side == "prediction":
            raise RuntimeError("prediction unavailable")
        return _expected()

    async def observe(_action: Action, expected: ExpectedEffect) -> ObservedEffect:
        if failure_side == "observation":
            raise RuntimeError("observation unavailable")
        return ObservedEffect(
            prediction_id=expected.prediction_id,
            target_ref=expected.target_ref,
            metric=expected.metric,
            value=1.0,
            observed_at=_NOW + timedelta(minutes=1),
        )

    expected_result = _result()
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=expected_result)
    audit = InMemoryStateStore()
    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observe,
    )

    result = await loop._dispatch_action(action=_action(), rule=_rule())
    entries = _audit_payloads(audit)
    entry = _entry(entries, "effect_verification.shadow")
    response_entry = _entry(entries, "measurement.action_outcome.v1")

    assert result is expected_result
    assert entry["verification_status"] == "hold"
    assert entry["verification_reason"] == f"{failure_side}_provider_failed"
    assert response_entry["label"] == "unscorable"
    assert response_entry["scorable"] is False
    assert "observed_at" not in response_entry


async def test_prediction_target_mismatch_skips_observer_and_holds() -> None:
    async def predict(_action: Action) -> ExpectedEffect:
        expected = _expected()
        return ExpectedEffect(
            prediction_id=expected.prediction_id,
            target_ref="resource:other",
            metric=expected.metric,
            acceptable_min=expected.acceptable_min,
            acceptable_max=expected.acceptable_max,
            predicted_at=expected.predicted_at,
            observation_deadline=expected.observation_deadline,
        )

    observer = AsyncMock()
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=_result())
    audit = InMemoryStateStore()
    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observer,
    )

    await loop._dispatch_action(action=_action(), rule=_rule())
    entry = _entry(_audit_payloads(audit), "measurement.action_outcome.v1")

    observer.assert_not_awaited()
    assert entry["verification_reason"] == "prediction_target_mismatch"
    assert entry["scorable"] is False


async def test_shadow_audit_failure_does_not_change_execution_result() -> None:
    async def predict(_action: Action) -> ExpectedEffect:
        return _expected()

    async def observe(_action: Action, expected: ExpectedEffect) -> ObservedEffect:
        return ObservedEffect(
            prediction_id=expected.prediction_id,
            target_ref=expected.target_ref,
            metric=expected.metric,
            value=1.0,
            observed_at=_NOW + timedelta(minutes=1),
        )

    expected_result = _result()
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=expected_result)
    audit = MagicMock()
    audit.append_audit_entry = AsyncMock(side_effect=RuntimeError("audit unavailable"))
    relay = AsyncMock()
    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observe,
        response_outcome_sink=relay,
    )

    result = await loop._dispatch_action(action=_action(), rule=_rule())

    assert result is expected_result
    relay.assert_not_awaited()
