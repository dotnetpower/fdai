from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel
from fdai.core.assurance_twin.model_promotion import (
    GraphModelEvidenceCohort,
    GraphModelPromotionReceipt,
    GraphModelRisk,
    graph_effect_model_digest,
    graph_effect_model_slot_digest,
)
from fdai.delivery.persistence.state_store_graph_model_promotion import (
    StateStoreGraphModelPromotionRegistry,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ONTOLOGY = "a" * 64
_SEMANTICS = "b" * 64


def _model(model_id: str, revision: int) -> GraphEffectModel:
    return GraphEffectModel(
        model_id=model_id,
        version="1.0.0",
        revision=revision,
        status=EffectModelStatus.CHALLENGER,
        trigger_ref="ops.scale-out",
        source_type="Service",
        link_path=("depends_on",),
        target_type="Database",
        target_metric="latency_ms",
        propagation_lag_seconds=30,
        gain=-0.2 - revision / 100.0,
        offset=0.0,
        interval_radius=0.05,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest=f"{revision:x}" * 64,
        learned_through=datetime(2026, 8, revision, tzinfo=UTC),
        sample_count=50,
        mean_absolute_error=0.02,
        applied_observation_digests=(f"{revision + 8:x}" * 64,),
    )


def _receipt(
    model: GraphEffectModel,
    *,
    expected_revision: int,
    rollback_model: GraphEffectModel | None,
) -> GraphModelPromotionReceipt:
    return GraphModelPromotionReceipt(
        model_id=model.model_id,
        model_version=model.version,
        model_revision=model.revision,
        model_digest=graph_effect_model_digest(model),
        slot_digest=graph_effect_model_slot_digest(model),
        ontology_release_digest=_ONTOLOGY,
        property_semantics_digest=_SEMANTICS,
        causal_receipt_digest=model.causal_evidence_receipt_digest,
        evidence_grade=model.evidence_grade,
        cohort=GraphModelEvidenceCohort.LIVE_SHADOW,
        risk=GraphModelRisk.STANDARD,
        sample_count=50,
        confidence_interval_lower=0.88,
        confidence_interval_upper=0.98,
        fidelity=0.94,
        recurrence_window_complete=True,
        recurrence_rate=0.0,
        policy_escapes=0,
        invariant_evidence_digests=("e" * 64,),
        expected_pointer_revision=expected_revision,
        rollback_model_ref=rollback_model.ref if rollback_model else None,
        rollback_model_digest=(
            graph_effect_model_digest(rollback_model) if rollback_model else None
        ),
        sealed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def _registry(
    store: InMemoryStateStore,
    *,
    ontology_release_digest: str = _ONTOLOGY,
) -> StateStoreGraphModelPromotionRegistry:
    return StateStoreGraphModelPromotionRegistry(
        store=store,
        ontology_release_digest=ontology_release_digest,
        property_semantics_digest=_SEMANTICS,
    )


async def _prepare(
    registry: StateStoreGraphModelPromotionRegistry,
    model: GraphEffectModel,
    receipt: GraphModelPromotionReceipt,
) -> None:
    await registry.save_artifact(model, recorded_by="Norns")
    await registry.save_receipt(receipt, recorded_by="Mimir")


async def test_restart_and_rollback_restore_the_prior_active_ref() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    prior = _model("graph-prior", 1)
    first_receipt = _receipt(prior, expected_revision=0, rollback_model=None)
    challenger = _model("graph-challenger", 2)
    promotion = _receipt(challenger, expected_revision=1, rollback_model=prior)

    async with asyncio.timeout(0.5):
        await _prepare(registry, prior, first_receipt)
        await registry.promote(first_receipt, actor="Thor")
        await _prepare(registry, challenger, promotion)
        promoted = await registry.promote(promotion, actor="Thor")

        restarted = _registry(store)
        restored = await restarted.load_active(promotion.slot_digest)
        assert restored == promoted.pointer
        assert restored.prior_active_model_ref == prior.ref

        rolled_back = await restarted.rollback(promotion, actor="Thor")

    assert rolled_back.pointer.active_model_ref == prior.ref
    assert rolled_back.pointer.active_model_digest == graph_effect_model_digest(prior)
    assert rolled_back.pointer.revision == 3
    assert await registry.load_artifact(promotion.model_digest) == challenger


async def test_concurrent_promotions_have_exactly_one_cas_winner() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    prior = _model("graph-prior", 1)
    first_receipt = _receipt(prior, expected_revision=0, rollback_model=None)
    left = _model("graph-left", 2)
    right = _model("graph-right", 3)
    left_receipt = _receipt(left, expected_revision=1, rollback_model=prior)
    right_receipt = _receipt(right, expected_revision=1, rollback_model=prior)

    async with asyncio.timeout(0.5):
        await _prepare(registry, prior, first_receipt)
        await registry.promote(first_receipt, actor="Thor")
        await _prepare(registry, left, left_receipt)
        await _prepare(registry, right, right_receipt)
        results = await asyncio.gather(
            registry.promote(left_receipt, actor="Thor"),
            registry.promote(right_receipt, actor="Thor"),
            return_exceptions=True,
        )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    pointer = await registry.load_active(first_receipt.slot_digest)
    assert pointer is not None
    assert pointer.revision == 2
    assert pointer.active_model_ref in {left.ref, right.ref}


async def test_inert_candidate_tamper_and_release_mismatch_fail_closed() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    challenger = _model("graph-challenger", 2)
    receipt = _receipt(challenger, expected_revision=0, rollback_model=None)

    async with asyncio.timeout(0.5):
        await _prepare(registry, challenger, receipt)
        assert await registry.load_active(receipt.slot_digest) is None

        mismatched_registry = _registry(store, ontology_release_digest="f" * 64)
        with pytest.raises(ValueError, match="semantic release mismatched"):
            await mismatched_registry.promote(receipt, actor="Thor")
        assert await registry.load_active(receipt.slot_digest) is None

        receipt_key = f"graph-model-promotion:receipt:{receipt.content_digest}"
        raw = await store.read_state(receipt_key)
        assert raw is not None
        tampered = dict(raw)
        tampered_receipt = dict(tampered["receipt"])
        tampered_receipt["fidelity"] = 0.91
        tampered["receipt"] = tampered_receipt
        await store.write_state(receipt_key, tampered)
        with pytest.raises(ValueError, match="receipt digest mismatched"):
            await registry.load_receipt(receipt.content_digest)


async def test_unknown_persisted_receipt_field_is_rejected_as_tampering() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    challenger = _model("graph-challenger", 2)
    receipt = _receipt(challenger, expected_revision=0, rollback_model=None)

    async with asyncio.timeout(0.5):
        await _prepare(registry, challenger, receipt)
        receipt_key = f"graph-model-promotion:receipt:{receipt.content_digest}"
        raw = await store.read_state(receipt_key)
        assert raw is not None
        tampered = dict(raw)
        tampered_receipt = dict(tampered["receipt"])
        tampered_receipt["unreviewed_override"] = True
        tampered["receipt"] = tampered_receipt
        await store.write_state(receipt_key, tampered)

        with pytest.raises(ValueError, match="fields do not match schema"):
            await registry.load_receipt(receipt.content_digest)


async def test_stale_receipt_cannot_replace_a_newer_active_pointer() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    first = _model("graph-first", 1)
    receipt = _receipt(first, expected_revision=0, rollback_model=None)

    async with asyncio.timeout(0.5):
        await _prepare(registry, first, receipt)
        await registry.promote(receipt, actor="Thor")
        stale_model = _model("graph-stale", 2)
        stale = replace(
            _receipt(stale_model, expected_revision=0, rollback_model=None),
            sealed_at=datetime(2026, 8, 11, tzinfo=UTC),
        )
        await _prepare(registry, stale_model, stale)
        with pytest.raises(ValueError, match="receipt is stale"):
            await registry.promote(stale, actor="Thor")

    pointer = await registry.load_active(receipt.slot_digest)
    assert pointer is not None
    assert pointer.active_model_ref == first.ref
