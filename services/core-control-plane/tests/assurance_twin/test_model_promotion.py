from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel
from fdai.core.assurance_twin.model_promotion import (
    GraphModelEvidenceCohort,
    GraphModelPromotionPolicy,
    GraphModelPromotionReceipt,
    GraphModelRisk,
    graph_effect_model_digest,
    graph_effect_model_slot_digest,
    validate_graph_model_promotion,
)

_ONTOLOGY = "a" * 64
_SEMANTICS = "b" * 64


def _model(*, evidence_grade: CausalEvidenceGrade) -> GraphEffectModel:
    return GraphEffectModel(
        model_id="graph-latency",
        version="1.0.0",
        revision=2,
        status=EffectModelStatus.CHALLENGER,
        trigger_ref="ops.scale-out",
        source_type="Service",
        link_path=("depends_on",),
        target_type="Database",
        target_metric="latency_ms",
        propagation_lag_seconds=30,
        gain=-0.2,
        offset=0.0,
        interval_radius=0.05,
        evidence_grade=evidence_grade,
        causal_evidence_receipt_digest="c" * 64,
        learned_through=datetime(2026, 8, 1, tzinfo=UTC),
        sample_count=50,
        mean_absolute_error=0.02,
        applied_observation_digests=("d" * 64,),
    )


def _receipt(model: GraphEffectModel, *, risk: GraphModelRisk) -> GraphModelPromotionReceipt:
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
        risk=risk,
        sample_count=50,
        confidence_interval_lower=0.88,
        confidence_interval_upper=0.98,
        fidelity=0.94,
        recurrence_window_complete=True,
        recurrence_rate=0.0,
        policy_escapes=0,
        invariant_evidence_digests=("e" * 64,),
        expected_pointer_revision=0,
        rollback_model_ref=None,
        rollback_model_digest=None,
        sealed_at=datetime(2026, 8, 2, tzinfo=UTC),
    )


def test_high_risk_policy_can_require_interventional_evidence() -> None:
    model = _model(evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL)
    receipt = _receipt(model, risk=GraphModelRisk.HIGH)

    with pytest.raises(ValueError, match="causal evidence is insufficient"):
        validate_graph_model_promotion(
            receipt=receipt,
            model=model,
            current_pointer=None,
            expected_ontology_release_digest=_ONTOLOGY,
            expected_property_semantics_digest=_SEMANTICS,
            policy=GraphModelPromotionPolicy(require_interventional_for_high_risk=True),
        )

    validate_graph_model_promotion(
        receipt=replace(receipt, risk=GraphModelRisk.STANDARD),
        model=model,
        current_pointer=None,
        expected_ontology_release_digest=_ONTOLOGY,
        expected_property_semantics_digest=_SEMANTICS,
        policy=GraphModelPromotionPolicy(require_interventional_for_high_risk=True),
    )


def test_promotion_receipt_digest_fixes_every_governed_evidence_field() -> None:
    model = _model(evidence_grade=CausalEvidenceGrade.INTERVENTIONAL)
    receipt = _receipt(model, risk=GraphModelRisk.HIGH)

    assert replace(receipt, fidelity=0.93).content_digest != receipt.content_digest
    assert (
        replace(receipt, ontology_release_digest="f" * 64).content_digest != receipt.content_digest
    )
    assert replace(receipt, policy_escapes=1).content_digest != receipt.content_digest
    assert replace(receipt, recurrence_rate=0.01).content_digest != receipt.content_digest
    assert replace(receipt, invariant_evidence_digests=("1" * 64,)).content_digest != (
        receipt.content_digest
    )
