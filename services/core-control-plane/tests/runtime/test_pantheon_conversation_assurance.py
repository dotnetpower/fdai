"""Focused runtime tests for authoritative Pantheon campaign turns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fdai.agents import PANTHEON_SPECS
from fdai.core.conversation_assurance import (
    AssuranceCriterion,
    ConversationAssuranceCoordinator,
    CriterionScore,
    EvaluatorOutput,
    InMemoryConversationAssuranceLedger,
    MixedFamilyAssuranceReviewer,
    TurnAssessmentInput,
    build_pantheon_census,
)
from fdai.runtime.pantheon_conversation_assurance import (
    RuntimePantheonConversationAssurance,
    runtime_source_identity,
)
from fdai_service_contracts import OperatorRole, SemanticTurnPrincipal, SemanticTurnRequest


class _Evaluator:
    prospective_cost_microusd = 1

    def __init__(self, identity: str, family: str) -> None:
        self.model_identity = identity
        self.model_family = family

    async def evaluate(
        self,
        turn: TurnAssessmentInput,
        *,
        debate: object | None = None,
    ) -> EvaluatorOutput:
        del debate
        return EvaluatorOutput(
            model_identity=self.model_identity,
            model_family=self.model_family,
            confidence=0.95,
            scores=tuple(
                CriterionScore(
                    criterion=criterion,
                    score=4,
                    rationale="Supported by the fixed diagnostic observation.",
                    evidence_refs=turn.evidence_refs,
                )
                for criterion in AssuranceCriterion
            ),
        )


class _Pantheon:
    async def ask(self, **values: object) -> object:
        case = build_pantheon_census(PANTHEON_SPECS).cases[0]
        assert values["question"] == case.question
        spec = PANTHEON_SPECS[0]
        prompt = spec.conversation_policy()
        evidence_digest = "c" * 64
        return SimpleNamespace(
            primary_agent=spec.name,
            decision=SimpleNamespace(
                method="explicit",
                semantic_score=None,
                semantic_margin=None,
                contributors=(),
            ),
            answer={
                "answer": "Odin owns bounded planning and has no execution authority.",
                "execution_authority": False,
                "pantheon_trace_fragment": {
                    "turn_digest": "d" * 64,
                    "session_digest": "e" * 64,
                    "correlation_digest": "f" * 64,
                    "handoff_owner": None,
                    "participants": [
                        {
                            "agent": spec.name,
                            "prompt_version": spec.conversation.version,
                            "prompt_sha256": prompt["prompt_sha256"],
                            "situation": "operator:direct:T1:en",
                        }
                    ],
                    "tool_ids": [],
                    "evidence_ref_digests": [evidence_digest],
                    "evidence_manifest_digest": "1" * 64,
                    "reported_verification_status": "verified",
                    "reported_verification_authority": "agent_owned_projection",
                },
            },
        )


async def test_runtime_persists_one_server_assembled_pantheon_diagnostic() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    reviewer = MixedFamilyAssuranceReviewer(
        first=_Evaluator("reviewer-a", "family-a"),
        second=_Evaluator("reviewer-b", "family-b"),
    )
    runtime = RuntimePantheonConversationAssurance(
        pantheon=_Pantheon(),  # type: ignore[arg-type]
        coordinator=ConversationAssuranceCoordinator(
            ledger=ledger,
            reviewer=reviewer,
            rubric_version="1.0.0",
        ),
        source_revision="a" * 40,
        source_content_digest="b" * 64,
    )
    case = build_pantheon_census(PANTHEON_SPECS).cases[0]
    request = SemanticTurnRequest(
        utterance=case.question,
        principal=SemanticTurnPrincipal(
            subject_id="operator-one",
            roles=(OperatorRole.READER,),
        ),
        session_id="pantheon-assurance:campaign-one",
        turn_id="turn-one",
        turn_sequence=0,
        locale=case.locale,
        purpose=f"conversation-assurance:{case.case_id}",
        deadline_at="2026-08-30T12:00:00Z",
    )

    result = await runtime.evaluate(request, case_id=case.case_id)

    diagnostic = result["pantheon_diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["score"] == 30
    assert diagnostic["verdict"] == "pass"
    stored = await ledger.list_assessments(principal_scope="operator-one")
    assert len(stored) == 1
    assert stored[0].decision.pantheon_diagnostic is not None


def test_configured_source_identity_is_complete_and_pinned(tmp_path) -> None:
    environment = {
        "FDAI_CONVERSATION_ASSURANCE_SOURCE_REVISION": "a" * 40,
        "FDAI_CONVERSATION_ASSURANCE_SOURCE_CONTENT_DIGEST": "b" * 64,
    }

    assert runtime_source_identity(tmp_path, environment) == ("a" * 40, "b" * 64)

    with pytest.raises(RuntimeError, match="configured together"):
        runtime_source_identity(
            tmp_path,
            {"FDAI_CONVERSATION_ASSURANCE_SOURCE_REVISION": "a" * 40},
        )
