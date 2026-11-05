from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel
from fdai.core.assurance_twin.model_promotion import (
    EFFECT_MODEL_ACTIVATION_EVIDENCE_PURPOSE,
    GraphModelActivePointer,
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
    validate_graph_model_promotion_evidence,
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


def test_active_pointer_and_policy_invariants() -> None:
    pointer = GraphModelActivePointer(
        slot_digest="1" * 64,
        revision=2,
        active_model_ref="graph-latency@1.0.0:r1",
        active_model_digest="2" * 64,
        prior_active_model_ref="graph-latency@1.0.0:r0",
        prior_active_model_digest="3" * 64,
        promotion_receipt_digest="4" * 64,
    )
    assert pointer.revision == 2

    with pytest.raises(ValueError, match="revision MUST be positive"):
        replace(pointer, revision=0)
    with pytest.raises(ValueError, match="MUST be SHA-256"):
        replace(pointer, slot_digest="invalid")
    with pytest.raises(ValueError, match="ref and digest MUST be present together"):
        replace(pointer, active_model_ref=None)
    with pytest.raises(ValueError, match="active pointer model is invalid"):
        replace(pointer, active_model_ref="", active_model_digest="2" * 64)
    with pytest.raises(ValueError, match="active pointer model MUST be SHA-256"):
        replace(pointer, active_model_ref="graph-latency@1.0.0:r1", active_model_digest="invalid")

    with pytest.raises(ValueError, match="count thresholds MUST be valid"):
        GraphModelPromotionPolicy(min_samples=0)
    with pytest.raises(ValueError, match="count thresholds MUST be valid"):
        GraphModelPromotionPolicy(max_policy_escapes=-1)
    with pytest.raises(ValueError, match="outside its declared bound"):
        GraphModelPromotionPolicy(min_fidelity=1.5)
    with pytest.raises(ValueError, match="evidence grade is invalid"):
        GraphModelPromotionPolicy(min_evidence_grade="interventional")  # type: ignore[arg-type]


def test_promotion_receipt_invariants() -> None:
    model = _model(evidence_grade=CausalEvidenceGrade.INTERVENTIONAL)
    receipt = _receipt(model, risk=GraphModelRisk.STANDARD)

    with pytest.raises(ValueError, match="model identity MUST be complete"):
        replace(receipt, model_id="")
    with pytest.raises(ValueError, match="counts MUST be valid"):
        replace(receipt, sample_count=0)
    with pytest.raises(ValueError, match="evidence rates MUST be in \\[0, 1\\]"):
        replace(receipt, fidelity=1.2)
    with pytest.raises(ValueError, match="fidelity MUST be inside its confidence interval"):
        replace(receipt, fidelity=0.80)
    with pytest.raises(ValueError, match="recurrence completeness MUST be boolean"):
        replace(receipt, recurrence_window_complete=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invariant evidence MUST be unique and bounded"):
        replace(receipt, invariant_evidence_digests=())
    with pytest.raises(ValueError, match="invariant evidence MUST use SHA-256"):
        replace(receipt, invariant_evidence_digests=("invalid",))
    with pytest.raises(ValueError, match="expected pointer revision MUST be non-negative"):
        replace(receipt, expected_pointer_revision=-1)
    with pytest.raises(ValueError, match="sealed_at MUST be timezone-aware"):
        replace(receipt, sealed_at=datetime(2026, 8, 2))


def test_validate_promotion_pointer_and_evidence_rejections() -> None:
    model = _model(evidence_grade=CausalEvidenceGrade.INTERVENTIONAL)
    receipt = _receipt(model, risk=GraphModelRisk.STANDARD)
    policy = GraphModelPromotionPolicy(
        min_samples=10,
        min_fidelity=0.90,
        max_recurrence_rate=0.05,
        max_policy_escapes=0,
    )

    pointer = GraphModelActivePointer(
        slot_digest=receipt.slot_digest,
        revision=1,
        active_model_ref="graph-latency@1.0.0:r1",
        active_model_digest="1" * 64,
        prior_active_model_ref=None,
        prior_active_model_digest=None,
        promotion_receipt_digest="2" * 64,
    )
    aligned_receipt = replace(
        receipt,
        expected_pointer_revision=1,
        rollback_model_ref=pointer.active_model_ref,
        rollback_model_digest=pointer.active_model_digest,
    )
    validate_graph_model_promotion(
        receipt=aligned_receipt,
        model=model,
        current_pointer=pointer,
        expected_ontology_release_digest=_ONTOLOGY,
        expected_property_semantics_digest=_SEMANTICS,
        policy=policy,
        decision_evidence=_admission(aligned_receipt),
        evaluated_at=_NOW,
    )

    with pytest.raises(ValueError, match="receipt is stale"):
        validate_graph_model_promotion(
            receipt=receipt,
            model=model,
            current_pointer=pointer,
            expected_ontology_release_digest=_ONTOLOGY,
            expected_property_semantics_digest=_SEMANTICS,
            policy=policy,
            decision_evidence=_admission(receipt),
            evaluated_at=_NOW,
        )

    active_model = replace(model, status=EffectModelStatus.ACTIVE)
    with pytest.raises(ValueError, match="only a challenger graph effect model can be promoted"):
        validate_graph_model_promotion_evidence(
            receipt=receipt,
            model=active_model,
            expected_ontology_release_digest=_ONTOLOGY,
            expected_property_semantics_digest=_SEMANTICS,
            policy=policy,
            decision_evidence=_admission(receipt),
            evaluated_at=_NOW,
        )

    mismatched_receipt = replace(receipt, model_version="2.0.0")
    with pytest.raises(ValueError, match="does not match its immutable model"):
        validate_graph_model_promotion_evidence(
            receipt=mismatched_receipt,
            model=model,
            expected_ontology_release_digest=_ONTOLOGY,
            expected_property_semantics_digest=_SEMANTICS,
            policy=policy,
            decision_evidence=_admission(mismatched_receipt),
            evaluated_at=_NOW,
        )

    with pytest.raises(ValueError, match="semantic release mismatched"):
        validate_graph_model_promotion_evidence(
            receipt=receipt,
            model=model,
            expected_ontology_release_digest="9" * 64,
            expected_property_semantics_digest=_SEMANTICS,
            policy=policy,
            decision_evidence=_admission(receipt),
            evaluated_at=_NOW,
        )

    failing_policy_receipt = replace(receipt, policy_escapes=2)
    with pytest.raises(ValueError, match="policy evidence failed"):
        validate_graph_model_promotion_evidence(
            receipt=failing_policy_receipt,
            model=model,
            expected_ontology_release_digest=_ONTOLOGY,
            expected_property_semantics_digest=_SEMANTICS,
            policy=policy,
            decision_evidence=_admission(failing_policy_receipt),
            evaluated_at=_NOW,
        )
