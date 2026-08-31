from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel
from fdai.core.assurance_twin.model_promotion import (
    EFFECT_MODEL_ACTIVATION_EVIDENCE_PURPOSE,
    GraphModelEvidenceCohort,
    GraphModelPromotionPolicy,
    GraphModelPromotionReceipt,
    GraphModelRisk,
    effect_model_activation_evidence_digest,
    effect_model_activation_rejection_reasons,
    effect_model_activation_scope_digest,
    graph_effect_model_digest,
    graph_effect_model_slot_digest,
    validate_graph_model_promotion,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

_ONTOLOGY = "a" * 64
_SEMANTICS = "b" * 64
_NOW = datetime(2026, 8, 3, tzinfo=UTC)
_BUNDLE_DIGEST = f"sha256:{'f' * 64}"


def _admission(
    receipt: GraphModelPromotionReceipt,
    **overrides: object,
) -> DecisionEvidenceAdmission:
    values: dict[str, object] = {
        "receipt_digest": _BUNDLE_DIGEST,
        "verification_bundle_digest": _BUNDLE_DIGEST,
        "evidence_digest": effect_model_activation_evidence_digest(receipt),
        "scope_digest": effect_model_activation_scope_digest(receipt),
        "purpose_id": EFFECT_MODEL_ACTIVATION_EVIDENCE_PURPOSE,
        "source_revision": _ONTOLOGY,
        "verified_at": datetime(2026, 8, 2, 12, tzinfo=UTC),
        "valid_until": datetime(2026, 8, 4, tzinfo=UTC),
    }
    values.update(overrides)
    return DecisionEvidenceAdmission(**values)  # type: ignore[arg-type]


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
            decision_evidence=_admission(receipt),
            evaluated_at=_NOW,
        )

    standard = replace(receipt, risk=GraphModelRisk.STANDARD)
    validate_graph_model_promotion(
        receipt=standard,
        model=model,
        current_pointer=None,
        expected_ontology_release_digest=_ONTOLOGY,
        expected_property_semantics_digest=_SEMANTICS,
        policy=GraphModelPromotionPolicy(require_interventional_for_high_risk=True),
        decision_evidence=_admission(standard),
        evaluated_at=_NOW,
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


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"purpose_id": "operational-promotion"}, "decision_evidence_purpose_mismatch"),
        ({"scope_digest": f"sha256:{'1' * 64}"}, "decision_evidence_scope_mismatch"),
        ({"evidence_digest": f"sha256:{'2' * 64}"}, "decision_evidence_evidence_mismatch"),
        ({"source_revision": "d" * 64}, "decision_evidence_source_revision_mismatch"),
        (
            {
                "verified_at": datetime(2026, 7, 1, tzinfo=UTC),
                "valid_until": datetime(2026, 7, 2, tzinfo=UTC),
            },
            "decision_evidence_not_current",
        ),
    ],
)
def test_a_mismatched_admission_blocks_effect_model_activation(
    overrides: dict[str, object],
    expected: str,
) -> None:
    model = _model(evidence_grade=CausalEvidenceGrade.INTERVENTIONAL)
    receipt = _receipt(model, risk=GraphModelRisk.STANDARD)

    assert effect_model_activation_rejection_reasons(
        receipt,
        decision_evidence=_admission(receipt, **overrides),
        expected_ontology_release_digest=_ONTOLOGY,
        evaluated_at=_NOW,
    ) == (expected,)

    with pytest.raises(ValueError, match="evidence admission failed"):
        validate_graph_model_promotion(
            receipt=receipt,
            model=model,
            current_pointer=None,
            expected_ontology_release_digest=_ONTOLOGY,
            expected_property_semantics_digest=_SEMANTICS,
            policy=GraphModelPromotionPolicy(),
            decision_evidence=_admission(receipt, **overrides),
            evaluated_at=_NOW,
        )


def test_a_missing_admission_blocks_effect_model_activation() -> None:
    model = _model(evidence_grade=CausalEvidenceGrade.INTERVENTIONAL)
    receipt = _receipt(model, risk=GraphModelRisk.STANDARD)

    assert effect_model_activation_rejection_reasons(
        receipt,
        decision_evidence=None,
        expected_ontology_release_digest=_ONTOLOGY,
        evaluated_at=_NOW,
    ) == ("decision_evidence_admission_missing",)

    with pytest.raises(ValueError, match="admission_missing"):
        validate_graph_model_promotion(
            receipt=receipt,
            model=model,
            current_pointer=None,
            expected_ontology_release_digest=_ONTOLOGY,
            expected_property_semantics_digest=_SEMANTICS,
            policy=GraphModelPromotionPolicy(),
            decision_evidence=None,
            evaluated_at=_NOW,
        )
