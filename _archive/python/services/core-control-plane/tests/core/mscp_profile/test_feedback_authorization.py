"""Effect mismatch and learning evidence never rewrite an earlier authorization."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.core.executor import ExecutionResult
from fdai.core.mscp_profile import ExpectedEffect, ObservedEffect
from fdai.shared.contracts.models import Action
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.mscp_profile.test_control_loop_shadow import (
    _NOW,
    _action,
    _audit_payloads,
    _entry,
    _expected,
    _loop,
    _result,
    _rule,
)


@pytest.mark.parametrize("decision", ["auto", "hil"])
@pytest.mark.parametrize("observed_value", [1.0, 0.98])
async def test_authorization_survives_independent_effect_verdict(
    decision: Literal["auto", "hil"], observed_value: float
) -> None:
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=_result())

    async def predict(action: Action) -> ExpectedEffect:
        return _expected()

    async def observe(action: Action, expected: ExpectedEffect) -> ObservedEffect:
        return ObservedEffect(
            expected.prediction_id,
            expected.target_ref,
            expected.metric,
            observed_value,
            _NOW + timedelta(minutes=1),
        )

    audit = InMemoryStateStore()
    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observe,
    )
    await loop._dispatch_action(action=_action(), rule=_rule(), authorization_decision=decision)
    outcome = _entry(_audit_payloads(audit), "measurement.action_outcome.v1")
    assert outcome["decision"] == decision
    assert outcome["label"] == ("verified" if observed_value == 1.0 else "mismatch")


async def test_frozen_prediction_is_persisted_before_execution_and_observation() -> None:
    import hashlib

    from fdai.shared.contracts.models import EffectPredictionSnapshot

    action = _action()
    expected = _expected()
    snapshot = EffectPredictionSnapshot(
        prediction_id=expected.prediction_id,
        event_id=action.event_id,
        action_id=action.action_id,
        action_type_id=action.action_type,
        target_digest=hashlib.sha256(action.target_resource_ref.encode()).hexdigest(),
        metric=expected.metric,
        unit="ratio",
        objective="maximize",
        model_ref="availability@1.0.0",
        model_digest="a" * 64,
        source_digest="b" * 64,
        independence_key="c" * 64,
        point_prediction=1.0,
        interval_lower=0.98,
        interval_upper=1.0,
        nominal_coverage=0.95,
        known_at=_NOW,
        predicted_at=_NOW,
        observation_deadline=expected.observation_deadline,
    )
    audit = InMemoryStateStore()
    executor = MagicMock()

    async def execute(**kwargs: object) -> ExecutionResult:
        entries = _audit_payloads(audit)
        assert (
            _entry(entries, "dynamic.effect_prediction.frozen")["snapshot_digest"]
            == snapshot.digest
        )
        return _result()

    executor.execute = AsyncMock(side_effect=execute)

    async def predict(action: Action) -> ExpectedEffect:
        return replace(expected, prediction_snapshot=snapshot)

    async def observe(action: Action, prediction: ExpectedEffect) -> ObservedEffect:
        return ObservedEffect(
            prediction.prediction_id,
            prediction.target_ref,
            prediction.metric,
            1.0,
            _NOW + timedelta(minutes=1),
            unit="ratio",
            receipt_ref="independent-observer:availability",
        )

    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observe,
    )
    await loop._dispatch_action(action=action, rule=_rule(), authorization_decision="auto")
    result = _entry(_audit_payloads(audit), "measurement.action_outcome.v1")
    assert result["schema_version"] == "1.1.0"
    assert result["prediction_snapshot"]["point_prediction"] == 1.0
    assert result["decision"] == "auto" and result["observation_unit"] == "ratio"


@pytest.mark.parametrize("retention", ["healthy", "unavailable", "identity_conflict"])
@pytest.mark.parametrize("invalid", ["unit", "receipt"])
async def test_optional_retention_failure_never_weakens_effect_verification(
    monkeypatch: pytest.MonkeyPatch, retention: str, invalid: str
) -> None:
    import hashlib

    from fdai.core.assurance_twin.prediction_evidence import retain_prediction
    from fdai.shared.contracts.models import EffectPredictionSnapshot

    action = _action()
    expected = _expected()
    snapshot = EffectPredictionSnapshot(
        prediction_id=expected.prediction_id,
        event_id=action.event_id,
        action_id=action.action_id,
        action_type_id=action.action_type,
        target_digest=hashlib.sha256(action.target_resource_ref.encode()).hexdigest(),
        metric=expected.metric,
        unit="ratio",
        objective="maximize",
        model_ref="availability@1.0.0",
        model_digest="a" * 64,
        source_digest="b" * 64,
        independence_key="c" * 64,
        point_prediction=1.0,
        interval_lower=0.98,
        interval_upper=1.0,
        nominal_coverage=0.95,
        known_at=_NOW,
        predicted_at=_NOW,
        observation_deadline=expected.observation_deadline,
    )
    audit = InMemoryStateStore()
    if retention == "identity_conflict":
        await retain_prediction(
            audit, snapshot.model_copy(update={"point_prediction": 0.99}), recorded_at=_NOW
        )
    if retention == "unavailable":

        async def unavailable(*args: object, **kwargs: object) -> bool:
            raise RuntimeError("prediction projection unavailable")

        monkeypatch.setattr(audit, "write_state_pair_with_audit_if_absent", unavailable)

    async def predict(action: Action) -> ExpectedEffect:
        return replace(expected, prediction_snapshot=snapshot)

    async def observe(action: Action, prediction: ExpectedEffect) -> ObservedEffect:
        return ObservedEffect(
            prediction.prediction_id,
            prediction.target_ref,
            prediction.metric,
            1.0,
            _NOW + timedelta(minutes=1),
            unit="ms" if invalid == "unit" else "ratio",
            receipt_ref=None if invalid == "receipt" else "independent-observer:availability",
        )

    executor = MagicMock()
    executor.execute = AsyncMock(return_value=_result())
    loop = _loop(
        executor=executor,
        audit_store=audit,
        expected_effect_provider=predict,
        effect_observer=observe,
    )
    result = await loop._dispatch_action(action=action, rule=_rule(), authorization_decision="auto")
    outcome = _entry(_audit_payloads(audit), "measurement.action_outcome.v1")
    assert outcome["label"] == "unscorable"
    assert result.audit_context["effect_verified"] is False
