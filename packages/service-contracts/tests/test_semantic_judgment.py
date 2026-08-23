from __future__ import annotations

import pytest
from pydantic import ValidationError

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticDiscourseMode,
    SemanticJudgmentProposal,
    SemanticJudgmentReceipt,
    SemanticJudgmentTier,
    SemanticTarget,
)

_DIGEST = "sha256:" + "a" * 64


def _proposal() -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal(
        primary_intent="resource.health",
        secondary_intents=("resource.activity",),
        targets=(
            SemanticTarget(kind="resource", value="example-vm", source_start=7, source_end=17),
        ),
        requested_facets=("health", "freshness"),
        confidence=0.94,
        ambiguous=False,
        action_subject="none",
        discourse_mode=SemanticDiscourseMode.DIRECT,
    )


def _receipt_body(proposal: SemanticJudgmentProposal) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "input_digest": _DIGEST,
        "context_digest": _DIGEST,
        "capability_digest": _DIGEST,
        "proposal_digest": proposal.proposal_digest,
        "profile_id": "operator.semantic",
        "profile_version": "1.0.0",
        "tier": "t1",
        "model_config_digest": _DIGEST,
        "prompt_digest": _DIGEST,
        "disposition": "accepted",
        "confidence": 0.94,
        "ambiguous": False,
        "latency_ms": 125,
        "reason_code": "semantic_judgment_accepted",
        "execution_authority": False,
    }


def test_proposal_carries_bounded_meaning_without_authority() -> None:
    proposal = _proposal()

    assert proposal.primary_intent == "resource.health"
    assert proposal.targets[0].value == "example-vm"
    assert proposal.execution_authority is False
    assert proposal.authority == "candidate_only"
    assert proposal.proposal_digest.startswith("sha256:")


def test_target_accepts_canonical_ontology_identity_case() -> None:
    target = SemanticTarget(
        kind="object_type",
        value="change",
        canonical_value="Change",
        source_start=0,
        source_end=6,
    )

    assert target.canonical_value == "Change"


def test_ambiguous_proposal_requires_one_question() -> None:
    proposal = SemanticJudgmentProposal(
        primary_intent="resource.status",
        confidence=0.61,
        ambiguous=True,
        action_subject="none",
        alternatives=("resource.health", "resource.lifecycle"),
        clarification="Do you mean health or lifecycle status?",
        discourse_mode=SemanticDiscourseMode.QUOTED,
    )

    assert proposal.ambiguous is True

    with pytest.raises(ValidationError, match="ambiguity MUST match"):
        SemanticJudgmentProposal(
            primary_intent="resource.status",
            confidence=0.61,
            ambiguous=False,
            action_subject="none",
            alternatives=("resource.health",),
        )


def test_accepted_receipt_requires_content_free_model_provenance() -> None:
    proposal = _proposal()
    body = _receipt_body(proposal)
    receipt = SemanticJudgmentReceipt(**body, receipt_digest=content_digest(body))

    assert receipt.tier is SemanticJudgmentTier.T1
    assert receipt.proposal_digest == proposal.proposal_digest
    assert receipt.execution_authority is False
    assert "example-vm" not in receipt.model_dump_json()


def test_unavailable_receipt_rejects_false_model_provenance() -> None:
    body = {
        "schema_version": "1.0.0",
        "input_digest": _DIGEST,
        "context_digest": _DIGEST,
        "capability_digest": _DIGEST,
        "proposal_digest": _DIGEST,
        "profile_id": "operator.semantic",
        "profile_version": "1.0.0",
        "tier": "t1",
        "model_config_digest": _DIGEST,
        "prompt_digest": _DIGEST,
        "disposition": "unavailable",
        "confidence": 0.0,
        "ambiguous": False,
        "latency_ms": 120_000,
        "reason_code": "semantic_model_unavailable",
        "execution_authority": False,
    }

    with pytest.raises(ValidationError, match="MUST NOT claim"):
        SemanticJudgmentReceipt(**body, receipt_digest=content_digest(body))


def test_contract_rejects_unknown_fields_and_execution_authority() -> None:
    with pytest.raises(ValidationError):
        SemanticJudgmentProposal(
            primary_intent="resource.health",
            confidence=1.0,
            ambiguous=False,
            action_subject="none",
            execution_authority=True,
        )
    with pytest.raises(ValidationError):
        SemanticJudgmentProposal(
            primary_intent="resource.health",
            confidence=1.0,
            ambiguous=False,
            action_subject="none",
            lexical_fallback="health",
        )


@pytest.mark.parametrize(
    ("action_posture", "action_subject"),
    [("advise_only", "Change"), ("draft_only", "none")],
)
def test_action_subject_must_match_action_posture(
    action_posture: str,
    action_subject: str,
) -> None:
    with pytest.raises(ValidationError, match="action subject MUST match draft posture"):
        SemanticJudgmentProposal(
            primary_intent="action_request",
            confidence=1.0,
            ambiguous=False,
            action_posture=action_posture,  # type: ignore[arg-type]
            action_subject=action_subject,  # type: ignore[arg-type]
        )
