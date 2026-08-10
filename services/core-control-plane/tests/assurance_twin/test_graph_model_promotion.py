from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModelStatus,
    GraphEffectModel,
    GraphEffectModelLifecycleConflictError,
    StateStoreGraphEffectModelLifecycleRegistry,
    StateStoreGraphEffectModelRegistry,
    graph_model_scope_digest,
)
from fdai.core.measurement import (
    GraphEffectModelPromotionPolicy,
    GraphEffectModelPromotionReceipt,
)
from fdai.delivery.graph_model_promotion import (
    DEMOTE_EFFECT_MODEL_ACTION_TYPE,
    PROMOTE_EFFECT_MODEL_ACTION_TYPE,
    GraphEffectModelPromotionDirectApiExecutor,
)
from fdai.delivery.persistence import StateStoreGraphEffectModelPromotionReceiptStore
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import DirectApiOutcome, DirectApiRequest
from fdai.shared.providers.testing import InMemoryStateStore

_NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _model(status: EffectModelStatus, *, revision: int = 1) -> GraphEffectModel:
    return GraphEffectModel(
        model_id=f"scale-database-availability-{status.value}",
        version="1.0.0",
        revision=revision,
        status=status,
        trigger_ref="action-type:ops.scale-out@1.0.0",
        source_type="compute.workload",
        link_path=("depends_on",),
        target_type="data.database",
        target_metric="availability",
        propagation_lag_seconds=60,
        gain=0.0,
        offset=0.0,
        interval_radius=0.01,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest="a" * 64,
        learned_through=datetime(2026, 8, 9, tzinfo=UTC),
        sample_count=40,
        mean_absolute_error=0.01,
        artifact_digest=("b" if status is EffectModelStatus.ACTIVE else "c") * 64,
        ontology_release_digest="d" * 64,
        property_semantics_digest="e" * 64,
        applicability_conditions=("environment=non-production",),
    )


def _receipt(
    challenger: GraphEffectModel,
    *,
    active_ref: str | None,
    scenario: str = "scale-out-v1",
    policy: GraphEffectModelPromotionPolicy | None = None,
) -> GraphEffectModelPromotionReceipt:
    return GraphEffectModelPromotionReceipt.create(
        model=challenger,
        fdai_revision="f" * 40,
        scenario_set_version=scenario,
        expected_active_ref=active_ref,
        rollback_ref=active_ref,
        frozen_scenario_set_digest="1" * 64,
        live_shadow_cohort_digest="2" * 64,
        distinct_observation_days=10,
        confidence_lower=0.95,
        confidence_upper=0.99,
        mean_absolute_percentage_error=0.02,
        within_tolerance_rate=0.96,
        rollback_rate=0.0,
        recurrence_rate=0.0,
        recurrence_window_complete=True,
        policy_escapes=0,
        invariant_violations=0,
        simulation_review_rate=0.0,
        evidence_cutoff=_NOW,
        policy=policy,
    )


async def _registries():  # type: ignore[no-untyped-def]
    store = InMemoryStateStore()
    models = StateStoreGraphEffectModelRegistry(store)
    active = _model(EffectModelStatus.ACTIVE)
    challenger = _model(EffectModelStatus.CHALLENGER)
    assert await models.register(active, registered_by="Mimir")
    assert await models.register(challenger, registered_by="Mimir")
    lifecycle = StateStoreGraphEffectModelLifecycleRegistry(store=store, models=models)
    return store, models, lifecycle, active, challenger


def test_promotion_receipt_requires_quasi_experimental_complete_evidence() -> None:
    challenger = _model(EffectModelStatus.CHALLENGER)
    receipt = _receipt(challenger, active_ref=_model(EffectModelStatus.ACTIVE).ref)

    assert receipt.ready is True
    assert receipt.gaps == ()
    assert (
        receipt.receipt_digest
        == GraphEffectModelPromotionReceipt.from_json(receipt.as_json()).receipt_digest
    )

    weak = _receipt(
        replace(challenger, evidence_grade=CausalEvidenceGrade.PREDICTIVE_PRECEDENCE),
        active_ref=_model(EffectModelStatus.ACTIVE).ref,
    )
    assert weak.ready is False
    assert "causal_evidence_grade_below_minimum" in weak.gaps


def test_promotion_receipt_rejects_tampered_content() -> None:
    receipt = _receipt(
        _model(EffectModelStatus.CHALLENGER),
        active_ref=_model(EffectModelStatus.ACTIVE).ref,
    )
    tampered = {**receipt.as_json(), "sample_count": receipt.sample_count + 1}

    with pytest.raises(ValueError, match="digest does not match"):
        GraphEffectModelPromotionReceipt.from_json(tampered)


async def test_lifecycle_promotes_by_cas_and_rollback_restores_prior_active() -> None:
    _, _, lifecycle, active, challenger = await _registries()
    receipt = _receipt(challenger, active_ref=active.ref)

    promoted = await lifecycle.promote(
        receipt=receipt,
        actor="Thor",
        promoted_at=_NOW,
    )
    selected = await lifecycle.list_models(
        status=EffectModelStatus.ACTIVE,
        trigger_refs=(challenger.trigger_ref,),
    )
    assert promoted.active_ref == challenger.ref
    assert promoted.rollback_ref == active.ref
    assert selected[0].ref == challenger.ref
    assert selected[0].status is EffectModelStatus.ACTIVE

    rolled_back = await lifecycle.rollback(
        scope_digest=promoted.scope_digest,
        expected_active_ref=challenger.ref,
        promotion_receipt_digest=receipt.receipt_digest,
        actor="Thor",
        rolled_back_at=_NOW,
    )
    selected = await lifecycle.list_models(
        status=EffectModelStatus.ACTIVE,
        trigger_refs=(challenger.trigger_ref,),
    )
    assert rolled_back.active_ref == active.ref
    assert selected[0].ref == active.ref


async def test_concurrent_stale_promotion_allows_only_one_receipt() -> None:
    _, _, lifecycle, active, challenger = await _registries()
    first = _receipt(challenger, active_ref=active.ref, scenario="scenario-a")
    second = _receipt(challenger, active_ref=active.ref, scenario="scenario-b")

    outcomes = await asyncio.gather(
        lifecycle.promote(receipt=first, actor="Thor", promoted_at=_NOW),
        lifecycle.promote(receipt=second, actor="Thor", promoted_at=_NOW),
        return_exceptions=True,
    )

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, GraphEffectModelLifecycleConflictError) for item in outcomes) == 1


async def test_first_promotion_rollback_clears_active_pointer() -> None:
    store = InMemoryStateStore()
    models = StateStoreGraphEffectModelRegistry(store)
    challenger = _model(EffectModelStatus.CHALLENGER)
    assert await models.register(challenger, registered_by="Mimir")
    lifecycle = StateStoreGraphEffectModelLifecycleRegistry(store=store, models=models)
    receipt = _receipt(challenger, active_ref=None)

    promoted = await lifecycle.promote(receipt=receipt, actor="Thor", promoted_at=_NOW)
    rolled_back = await lifecycle.rollback(
        scope_digest=promoted.scope_digest,
        expected_active_ref=challenger.ref,
        promotion_receipt_digest=receipt.receipt_digest,
        actor="Thor",
        rolled_back_at=_NOW,
    )

    assert promoted.rollback_ref is None
    assert rolled_back.active_ref is None
    assert (
        await lifecycle.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(challenger.trigger_ref,),
        )
        == ()
    )


async def test_lifecycle_rejects_receipt_with_mismatched_artifact_identity() -> None:
    _, _, lifecycle, active, challenger = await _registries()
    receipt = replace(
        _receipt(challenger, active_ref=active.ref),
        model_artifact_digest="9" * 64,
    )

    with pytest.raises(ValueError, match="does not match challenger identity"):
        await lifecycle.promote(receipt=receipt, actor="Thor", promoted_at=_NOW)


async def test_legacy_model_without_governed_identity_is_unpromotable() -> None:
    legacy = replace(
        _model(EffectModelStatus.CHALLENGER),
        artifact_digest=None,
        ontology_release_digest=None,
        property_semantics_digest=None,
        applicability_conditions=(),
    )

    assert legacy.promotable is False
    with pytest.raises(ValueError, match="lacks governed artifact identity"):
        _receipt(legacy, active_ref=None)


async def test_direct_api_shadow_never_mutates_and_enforce_promotes_then_demotes() -> None:
    store, _, lifecycle, active, challenger = await _registries()
    receipt = _receipt(challenger, active_ref=active.ref)
    receipts = StateStoreGraphEffectModelPromotionReceiptStore(store)
    assert await receipts.store(receipt)
    executor = GraphEffectModelPromotionDirectApiExecutor(
        receipts=receipts,
        lifecycle=lifecycle,
    )
    promote_arguments = {
        "model_ref": challenger.ref,
        "fdai_revision": receipt.fdai_revision,
        "scenario_set_version": receipt.scenario_set_version,
        "receipt_digest": receipt.receipt_digest,
        "justification": "reviewed model fidelity evidence",
    }
    shadow = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000501"),
        idempotency_key="graph-model-shadow",
        action_type_name=PROMOTE_EFFECT_MODEL_ACTION_TYPE,
        rule_ids=(),
        resource_ref=graph_model_scope_digest(challenger),
        arguments=promote_arguments,
        mode=Mode.SHADOW,
    )

    assert (await executor.execute(shadow)).outcome is DirectApiOutcome.SUCCEEDED
    assert (
        await lifecycle.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(challenger.trigger_ref,),
        )
    )[0].ref == active.ref

    enforce = replace(
        shadow,
        idempotency_key="graph-model-enforce",
        labels=("shadow", "enforce"),
        mode=Mode.ENFORCE,
    )
    assert (await executor.execute(enforce)).outcome is DirectApiOutcome.SUCCEEDED
    scope_digest = graph_model_scope_digest(challenger)
    demote = replace(
        enforce,
        action_id=UUID("00000000-0000-0000-0000-000000000502"),
        idempotency_key="graph-model-demote",
        action_type_name=DEMOTE_EFFECT_MODEL_ACTION_TYPE,
        arguments={
            "scope_digest": scope_digest,
            "expected_active_ref": challenger.ref,
            "promotion_receipt_digest": receipt.receipt_digest,
            "justification": "reviewed fidelity regression rollback",
        },
    )
    assert (await executor.execute(demote)).outcome is DirectApiOutcome.SUCCEEDED
    selected = await lifecycle.list_models(
        status=EffectModelStatus.ACTIVE,
        trigger_refs=(challenger.trigger_ref,),
    )
    assert selected[0].ref == active.ref
