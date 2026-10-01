from __future__ import annotations

import pytest
from pydantic import ValidationError

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticDirectResponseDraft,
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


def test_default_document_mode_is_omitted_from_legacy_digest_material() -> None:
    payload = _proposal().model_dump(mode="json")

    assert "document_evidence_mode" not in payload
    assert "forbidden_actions" not in payload
    replay = SemanticJudgmentProposal.model_validate({**payload, "forbidden_actions": []})
    assert replay.proposal_digest == _proposal().proposal_digest


def test_target_accepts_canonical_ontology_identity_case() -> None:
    target = SemanticTarget(
        kind="object_type",
        value="change",
        canonical_value="Change",
        source_start=0,
        source_end=6,
    )

    assert target.canonical_value == "Change"


def test_proposal_preserves_typed_forbidden_action_without_action_authority() -> None:
    proposal = _proposal().model_copy(
        update={
            "schema_version": "1.1.0",
            "forbidden_actions": (
                SemanticTarget(
                    kind="action_type",
                    value="재시작",
                    canonical_value="ops.restart-service",
                    source_start=14,
                    source_end=17,
                ),
            ),
        }
    )

    assert proposal.forbidden_actions[0].value == "재시작"
    assert proposal.action_posture == "advise_only"
    assert proposal.action_subject == "none"
    assert proposal.execution_authority is False


def test_v1_proposal_rejects_forbidden_actions() -> None:
    with pytest.raises(ValidationError, match="require schema 1.1.0"):
        SemanticJudgmentProposal(
            primary_intent="resource.health",
            confidence=1.0,
            ambiguous=False,
            action_subject="none",
            forbidden_actions=(
                SemanticTarget(
                    kind="action",
                    value="재시작",
                    source_start=0,
                    source_end=3,
                ),
            ),
        )


def test_constraint_slots_require_v13_and_legacy_payloads_keep_current_behavior() -> None:
    payload = {
        "schema_version": "1.3.0",
        "primary_intent": "resource.health",
        "confidence": 0.94,
        "ambiguous": False,
        "action_subject": "none",
        "constraint_slots": (
            {
                "role": "time_window",
                "source_start": 5,
                "source_end": 13,
                "grounded": True,
                "value": "PT24H",
            },
        ),
    }

    proposal = SemanticJudgmentProposal.model_validate(payload)
    legacy = SemanticJudgmentProposal(
        primary_intent="resource.health",
        confidence=0.94,
        ambiguous=False,
        action_subject="none",
    )

    assert proposal.constraint_slots[0].value == "PT24H"
    assert legacy.constraint_slots == ()
    with pytest.raises(ValidationError, match="schema 1.3.0"):
        SemanticJudgmentProposal.model_validate({**payload, "schema_version": "1.2.0"})


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


def test_direct_response_requires_one_bounded_model_authored_answer() -> None:
    draft = SemanticDirectResponseDraft(
        locale="ko",
        answer="반갑습니다. 무엇을 함께 살펴볼까요?",
        profile_digest=_DIGEST,
    )
    proposal = SemanticJudgmentProposal(
        primary_intent="greeting",
        confidence=0.98,
        ambiguous=False,
        action_subject="none",
        direct_response=draft,
    )

    assert proposal.direct_response is draft
    with pytest.raises(ValidationError, match="model-authored answer"):
        SemanticJudgmentProposal(
            primary_intent="greeting",
            confidence=0.98,
            ambiguous=False,
            action_subject="none",
        )
    with pytest.raises(ValidationError, match="one paragraph"):
        SemanticDirectResponseDraft(
            locale="en",
            answer="Hello.\nHow can I help?",
            profile_digest=_DIGEST,
        )
    with pytest.raises(ValidationError, match="links or markup"):
        SemanticDirectResponseDraft(
            locale="en",
            answer="Open [this](https://example.com).",
            profile_digest=_DIGEST,
        )
    with pytest.raises(ValidationError, match="links or markup"):
        SemanticDirectResponseDraft(
            locale="en",
            answer="Visit www.example.com or read **important** text.",
            profile_digest=_DIGEST,
        )
    with pytest.raises(ValidationError, match="polite honorific endings"):
        SemanticDirectResponseDraft(
            locale="ko",
            answer="안녕 반가워",
            profile_digest=_DIGEST,
        )
    with pytest.raises(ValidationError, match="polite honorific endings"):
        SemanticDirectResponseDraft(
            locale="ko",
            answer="안녕, 난 Bragi야！ 무엇을 도와드릴까요?",
            profile_digest=_DIGEST,
        )
    with pytest.raises(ValidationError, match="polite honorific endings"):
        SemanticDirectResponseDraft(
            locale="ko",
            answer="안녕 반가워.감사합니다.",
            profile_digest=_DIGEST,
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


@pytest.mark.parametrize(
    ("primary_intent", "discourse_mode"),
    [
        ("action_request", "quoted"),
        ("action_request", "hypothetical"),
        ("query.resource_current_state", "direct"),
    ],
)
def test_non_direct_and_query_meaning_cannot_become_draft(
    primary_intent: str,
    discourse_mode: str,
) -> None:
    with pytest.raises(ValidationError):
        SemanticJudgmentProposal(
            primary_intent=primary_intent,
            confidence=1.0,
            ambiguous=False,
            discourse_mode=discourse_mode,  # type: ignore[arg-type]
            action_posture="draft_only",
            action_subject="ActionType",
        )


def test_non_direct_discourse_cannot_manufacture_forbidden_action() -> None:
    with pytest.raises(ValidationError, match="MUST NOT create forbidden actions"):
        SemanticJudgmentProposal(
            schema_version="1.1.0",
            primary_intent="explanation",
            confidence=1.0,
            ambiguous=False,
            discourse_mode="quoted",
            action_subject="none",
            forbidden_actions=(
                SemanticTarget(
                    kind="action",
                    value="삭제",
                    source_start=6,
                    source_end=8,
                ),
            ),
        )


def test_forbidden_action_requires_action_kind() -> None:
    with pytest.raises(ValidationError, match="MUST use an action kind"):
        SemanticJudgmentProposal(
            schema_version="1.1.0",
            primary_intent="resource.status",
            confidence=1.0,
            ambiguous=False,
            action_subject="none",
            forbidden_actions=(
                SemanticTarget(
                    kind="resource",
                    value="삭제",
                    source_start=0,
                    source_end=2,
                ),
            ),
        )
