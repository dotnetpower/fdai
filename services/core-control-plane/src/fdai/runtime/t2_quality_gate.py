"""Compose the T2 quality gate, including receipt-driven rubric modes."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.composition import Container
from fdai.core.quality_gate import (
    HashedRuleEmbeddingIndex,
    QualityGate,
    QualityGateConfig,
    RagGroundingSource,
    RuleBasedVerifier,
)
from fdai.core.quality_gate.deterministic_evidence import (
    DeterministicEvidenceKind,
    DeterministicEvidenceVerifier,
)
from fdai.core.quality_gate.promotion import (
    ActionModeSource,
    RubricModeResolver,
    RubricPromotionRegistry,
)
from fdai.shared.contracts.models import Rule


def build_rubric_mode_resolver(
    container: Container,
    action_modes: ActionModeSource,
) -> RubricModeResolver | None:
    """Return a receipt-driven rubric resolver only when the deployment binds its evidence.

    ``Container`` accepts the receipt source and verifier only as a pair. Binding them is the
    deployment's explicit opt-in: the rubric leg can then leave shadow for one ActionType only when
    that ActionType already enforces and a current, independently verified receipt binds the same
    revision and identity. Without the pair, no resolver exists and the leg stays in shadow.
    """
    source = container.rubric_promotion_receipt_source
    verifier = container.rubric_promotion_receipt_verifier
    if source is None or verifier is None:
        return None
    return RubricPromotionRegistry(
        action_modes=action_modes,
        receipt_verifier=verifier,
        receipt_source=source,
    )


def build_t2_quality_gate(
    container: Container,
    *,
    rules_by_id: Mapping[str, Rule],
    action_modes: ActionModeSource,
    deterministic_evidence_verifiers: (
        Mapping[DeterministicEvidenceKind, DeterministicEvidenceVerifier] | None
    ),
) -> QualityGate:
    """Build the production T2 gate from container bindings and the active rule set."""
    llm_bindings = container.require_llm_bindings()
    rubric_mode_resolver = build_rubric_mode_resolver(container, action_modes)
    return QualityGate(
        verifier=RuleBasedVerifier(rules_by_id=dict(rules_by_id)),
        cross_check_models=llm_bindings.cross_check_models,
        grounding=RagGroundingSource(
            rules=dict(rules_by_id),
            embedding_index=HashedRuleEmbeddingIndex(),
        ),
        rubric_evaluator=llm_bindings.rubric_evaluator,
        rubric_mode_resolver=rubric_mode_resolver,
        deterministic_evidence_verifiers=deterministic_evidence_verifiers,
        config=QualityGateConfig(
            confidence_threshold=container.config.llm.quality_gate_confidence_threshold,
            require_cross_check_quorum=container.config.llm.quality_gate_quorum,
            # The configured ceiling stays shadow unless the receipt evidence pair is bound.
            rubric_shadow=rubric_mode_resolver is None,
        ),
    )


__all__ = ["build_rubric_mode_resolver", "build_t2_quality_gate"]
