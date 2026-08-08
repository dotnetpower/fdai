from __future__ import annotations

import pytest
from fdai.core.measurement import OperationalPromotionReceipt
from fdai.delivery.persistence import StateStoreOperationalPromotionReceiptStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REVISION = "a" * 40
_SCENARIO = "scenario-v1"
_ACTION = "remediate.tag-add"
_EVIDENCE = "b" * 64
_ACTION_DIGEST = "c" * 64
_KEY = f"operational-promotion-receipt:{_ACTION}:{_REVISION}:{_SCENARIO}:{_EVIDENCE}"


def _receipt() -> OperationalPromotionReceipt:
    return OperationalPromotionReceipt(
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
        action_type_name=_ACTION,
        action_type_version="1.0.0",
        action_type_digest=_ACTION_DIGEST,
        evidence_digest=_EVIDENCE,
        observation_days=14.0,
        live_observation_days=14,
        sample_count=100,
        benchmark_samples=50,
        live_shadow_samples=50,
        correct_count=100,
        accuracy=1.0,
        accuracy_ci_lower=0.96,
        accuracy_ci_upper=1.0,
        benchmark_accuracy=1.0,
        benchmark_accuracy_ci_lower=0.92,
        benchmark_accuracy_ci_upper=1.0,
        live_shadow_accuracy=1.0,
        live_shadow_accuracy_ci_lower=0.92,
        live_shadow_accuracy_ci_upper=1.0,
        policy_escapes=0,
        rollback_rate=0.0,
        recurrence_rate=0.0,
        executed_samples=50,
        recurrence_complete_samples=50,
        recurrence_incomplete_samples=0,
        simulation_review_rate=0.0,
        causal_evidence_failures=0,
        ready=True,
        gaps=(),
    )


async def test_receipt_store_round_trips_idempotently_with_one_audit() -> None:
    state = InMemoryStateStore()
    receipts = StateStoreOperationalPromotionReceiptStore(state)

    await receipts.save(_receipt())
    await receipts.save(_receipt())
    loaded = await receipts.load(
        action_type_name=_ACTION,
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
        evidence_digest=_EVIDENCE,
    )

    assert loaded == _receipt()
    assert len(state.audit_entries) == 1
    assert state.audit_entries[0]["entry"]["action_kind"] == (
        "operational_promotion.receipt_stored"
    )


async def test_receipt_store_rejects_tampered_numeric_types() -> None:
    state = InMemoryStateStore()
    receipts = StateStoreOperationalPromotionReceiptStore(state)
    payload = _receipt().as_json()
    payload["sample_count"] = "100"
    await state.write_state(
        _KEY,
        {"schema_version": "1.0.0", "receipt": payload},
    )

    with pytest.raises(ValueError, match="sample_count"):
        await receipts.load(
            action_type_name=_ACTION,
            fdai_revision=_REVISION,
            scenario_set_version=_SCENARIO,
            evidence_digest=_EVIDENCE,
        )
