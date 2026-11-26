from __future__ import annotations

import hashlib

from fdai.core.conversation_assurance import PolicyStage, PolicyTransition
from fdai.delivery.persistence.postgres_conversation_assurance_policy import (
    _same_transition_request,
    _transition,
    _transition_key,
)


def _admitted_transition() -> PolicyTransition:
    return PolicyTransition(
        candidate_id="candidate-1",
        from_stage=PolicyStage.SHADOW,
        to_stage=PolicyStage.CANARY_1,
        reasons=("promotion_guards_passed",),
        evidence_digest="e" * 64,
        decision_evidence_receipt_digest="sha256:" + "d" * 64,
        decision_evidence_verification_bundle_digest="sha256:" + "f" * 64,
    )


def test_transition_round_trip_preserves_decision_evidence_bindings() -> None:
    transition = _admitted_transition()

    restored = _transition(
        {
            "candidate_id": transition.candidate_id,
            "from_stage": transition.from_stage.value,
            "to_stage": transition.to_stage.value,
            "reasons": list(transition.reasons),
            "evidence_digest": transition.evidence_digest,
            "decision_evidence_receipt_digest": transition.decision_evidence_receipt_digest,
            "decision_evidence_verification_bundle_digest": (
                transition.decision_evidence_verification_bundle_digest
            ),
        }
    )

    assert restored == transition


def test_transition_key_stays_stable_when_decision_evidence_is_added() -> None:
    transition = _admitted_transition()
    held = PolicyTransition(
        candidate_id=transition.candidate_id,
        from_stage=transition.from_stage,
        to_stage=transition.to_stage,
        reasons=transition.reasons,
        evidence_digest=transition.evidence_digest,
    )

    assert _transition_key(transition) == _transition_key(held)


def test_transition_key_preserves_legacy_derivation_without_decision_evidence() -> None:
    transition = PolicyTransition(
        candidate_id="candidate-1",
        from_stage=PolicyStage.SHADOW,
        to_stage=PolicyStage.SHADOW,
        reasons=("decision_evidence_admission_missing",),
        evidence_digest="e" * 64,
    )
    legacy_material = "\0".join(
        (
            transition.candidate_id,
            transition.from_stage.value,
            transition.to_stage.value,
            *transition.reasons,
            transition.evidence_digest,
        )
    )

    assert _transition_key(transition) == hashlib.sha256(legacy_material.encode()).hexdigest()


def test_legacy_transition_without_stored_evidence_replays_as_safe_no_op() -> None:
    requested = _admitted_transition()
    legacy = PolicyTransition(
        candidate_id=requested.candidate_id,
        from_stage=requested.from_stage,
        to_stage=requested.to_stage,
        reasons=requested.reasons,
        evidence_digest=requested.evidence_digest,
    )

    assert _same_transition_request(legacy, requested)
    assert not _same_transition_request(requested, legacy)
