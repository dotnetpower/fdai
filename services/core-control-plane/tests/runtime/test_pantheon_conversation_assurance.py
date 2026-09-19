"""Focused runtime tests for authoritative Pantheon campaign turns."""

from __future__ import annotations

import json
import os
from dataclasses import replace
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
    parse_pantheon_corpus,
)
from fdai.runtime.conversation_assurance import runtime_assurance_corpus
from fdai.runtime.pantheon_assurance_evidence import hard_zero_violations
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
        self.turns: list[TurnAssessmentInput] = []

    async def evaluate(
        self,
        turn: TurnAssessmentInput,
        *,
        debate: object | None = None,
    ) -> EvaluatorOutput:
        del debate
        self.turns.append(turn)
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
        assert values["locale"] == case.locale
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


class _SemanticallyHeldPantheon(_Pantheon):
    async def ask(self, **values: object) -> object:
        turn = await super().ask(**values)
        turn.answer["answer"] = None
        turn.answer["abstain_reason"] = "semantic_unavailable"
        turn.answer["semantic_judgment"] = {
            "disposition": "abstained",
            "reason_code": "proposal_invalid",
            "model_identity": "narrator-gpt-5-4-mini",
        }
        return turn


class _AcceptedWithoutAnswerPantheon(_Pantheon):
    async def ask(self, **values: object) -> object:
        turn = await super().ask(**values)
        turn.answer["answer"] = None
        turn.answer["semantic_judgment"] = {
            "disposition": "accepted",
            "reason_code": "accepted",
        }
        return turn


class _DeliberatingPantheon:
    def __init__(self) -> None:
        self.fixed_assurance_facts: object = None

    async def deliberate(self, **values: object) -> dict[str, object]:
        assert values["reuse_semantic_route"] is False
        self.fixed_assurance_facts = values.get("fixed_assurance_facts")
        return {
            "status": "completed",
            "tier": "T1",
            "primary_agent": "Odin",
            "participants": [],
            "rounds": [],
            "conclusion": "The bounded T2 synthesis preserves the attributed evidence.",
            "semantic_score": 0.9,
            "semantic_margin": 0.2,
            "routing_method": "t1_semantic",
            "t1_evaluation": {
                "reason": "structured_conflict",
                "signal_count": 2,
                "conflicts": [{"field": "state"}],
            },
            "t2_status": "completed",
            "t2_model_family": "family-c",
            "t2_model_identity": "publisher-c:synthesizer-a",
            "metering_receipt_digest": "c" * 64,
        }


class _HeldDeliberatingPantheon:
    async def deliberate(self, **values: object) -> dict[str, object]:
        assert values["reuse_semantic_route"] is False
        return {
            "status": "completed",
            "tier": "T1",
            "primary_agent": "Odin",
            "participants": [],
            "rounds": [],
            "conclusion": "The T1 conclusion is preserved while T2 remains unavailable.",
            "semantic_score": 0.9,
            "semantic_margin": 0.2,
            "routing_method": "t1_semantic",
            "t1_evaluation": {
                "reason": "structured_conflict",
                "signal_count": 2,
                "conflicts": [{"field": "state"}],
            },
            "t2_status": "budget_denied",
        }


def test_pantheon_hard_zero_detects_deployment_scope_identifiers() -> None:
    leaked = "Tracked scope subscriptions/00000000-0000-0000-0000-000000000001."

    assert set(hard_zero_violations({}, leaked)) == {
        "hidden_scope_leak",
        "sensitive_output",
    }
    assert hard_zero_violations({}, "Evidence: agent-state:Njord:sha256:" + "a" * 64) == ()


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
    assert result["assessment_state"] == "completed"
    assert result["assessment_reasons"] == ["mixed_family_consensus"]
    assert result["answer_generation"] == {
        "mode": "agent_projection",
        "model_identity": None,
        "model_family": None,
    }
    assert result["pantheon_evaluator_models"] == [
        {
            "model_identity": "reviewer-a",
            "model_family": "family-a",
            "output_available": True,
        },
        {
            "model_identity": "reviewer-b",
            "model_family": "family-b",
            "output_available": True,
        },
    ]
    stored = await ledger.list_assessments(principal_scope="operator-one")
    assert len(stored) == 1
    assert stored[0].decision.pantheon_diagnostic is not None


async def test_runtime_preserves_semantic_hold_reason_without_answer_attribution() -> None:
    evaluator = _Evaluator("narrator-gpt-5-4-mini", "family-a")
    runtime = RuntimePantheonConversationAssurance(
        pantheon=_SemanticallyHeldPantheon(),  # type: ignore[arg-type]
        coordinator=ConversationAssuranceCoordinator(
            ledger=InMemoryConversationAssuranceLedger(),
            reviewer=MixedFamilyAssuranceReviewer(
                first=evaluator,
                second=_Evaluator("reviewer-b", "family-b"),
            ),
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
        turn_id="turn-held",
        turn_sequence=0,
        locale=case.locale,
        purpose=f"conversation-assurance:{case.case_id}",
        deadline_at="2026-08-30T12:00:00Z",
    )

    result = await runtime.evaluate(request, case_id=case.case_id)

    assert result["answer"] == "Pantheon abstained: proposal_invalid."
    assert result["answer_generation"] == {
        "mode": "agent_projection",
        "model_identity": None,
        "model_family": None,
    }
    assert len(evaluator.turns) == 1
    assert result["assessment_reasons"] == ["mixed_family_consensus"]


async def test_runtime_does_not_render_accepted_judgment_as_abstention() -> None:
    runtime = RuntimePantheonConversationAssurance(
        pantheon=_AcceptedWithoutAnswerPantheon(),  # type: ignore[arg-type]
        coordinator=ConversationAssuranceCoordinator(
            ledger=InMemoryConversationAssuranceLedger(),
            reviewer=MixedFamilyAssuranceReviewer(
                first=_Evaluator("reviewer-a", "family-a"),
                second=_Evaluator("reviewer-b", "family-b"),
            ),
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
        turn_id="turn-accepted",
        turn_sequence=0,
        locale=case.locale,
        purpose=f"conversation-assurance:{case.case_id}",
        deadline_at="2026-08-30T12:00:00Z",
    )

    with pytest.raises(RuntimeError, match="Pantheon answer is unavailable"):
        await runtime.evaluate(request, case_id=case.case_id)


async def test_t2_diagnostic_binds_trusted_fixed_scenario_before_review() -> None:
    first = _Evaluator("reviewer-a", "family-a")
    second = _Evaluator("reviewer-b", "family-b")
    pantheon = _DeliberatingPantheon()
    runtime = RuntimePantheonConversationAssurance(
        pantheon=pantheon,  # type: ignore[arg-type]
        coordinator=ConversationAssuranceCoordinator(
            ledger=InMemoryConversationAssuranceLedger(),
            reviewer=MixedFamilyAssuranceReviewer(first=first, second=second),
            rubric_version="1.0.0",
        ),
        source_revision="a" * 40,
        source_content_digest="b" * 64,
    )
    case = next(
        item
        for item in build_pantheon_census(PANTHEON_SPECS).cases
        if item.case_id == "t2-conflict-en"
    )
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

    trace = result["pantheon_trace"]
    assert isinstance(trace, dict)
    assert trace["t2_required"] is True
    assert trace["t2_attempted"] is True
    assert trace["t2_status"] == "completed"
    assert trace["routing_method"] == "t1_semantic"
    assert trace["verification_status"] == "unverified"
    assert trace["verification_authority"] == "pantheon_owned_projection"
    assert len(trace["evidence_ref_digests"]) == 0
    assert pantheon.fixed_assurance_facts == {
        "Freyr": {
            "scope_ref": "fixed-t2-scenario",
            "status": "consistent",
        },
        "Njord": {
            "scope_ref": "fixed-t2-scenario",
            "status": "conflicting",
        },
        "Odin": {
            "scope_ref": "fixed-t2-scenario",
            "status": "conflicting",
        },
    }
    assert len(result["pantheon_semantic_reviews"]) == 2
    assert first.turns == second.turns
    assert first.turns[0].answer_model_identity == "publisher-c:synthesizer-a"
    assert first.turns[0].answer_model_family == "family-c"
    assert "expected_t2=required" in first.turns[0].reference_facts
    assert result["answer_generation"] == {
        "mode": "t2_model",
        "model_identity": "publisher-c:synthesizer-a",
        "model_family": "family-c",
    }


async def test_external_t2_case_does_not_receive_fixed_scenario_facts() -> None:
    pantheon = _DeliberatingPantheon()
    fixed_case = next(
        item
        for item in build_pantheon_census(PANTHEON_SPECS).cases
        if item.case_id == "t2-conflict-en"
    )
    external_case = replace(fixed_case, case_id="external-t2")
    runtime = RuntimePantheonConversationAssurance(
        pantheon=pantheon,  # type: ignore[arg-type]
        coordinator=ConversationAssuranceCoordinator(
            ledger=InMemoryConversationAssuranceLedger(),
            reviewer=MixedFamilyAssuranceReviewer(
                first=_Evaluator("reviewer-a", "family-a"),
                second=_Evaluator("reviewer-b", "family-b"),
            ),
            rubric_version="1.0.0",
        ),
        source_revision="a" * 40,
        source_content_digest="b" * 64,
        additional_cases=(external_case,),
    )
    request = SemanticTurnRequest(
        utterance=external_case.question,
        principal=SemanticTurnPrincipal(
            subject_id="operator-one",
            roles=(OperatorRole.READER,),
        ),
        session_id="pantheon-assurance:campaign-one",
        turn_id="turn-external",
        turn_sequence=0,
        locale=external_case.locale,
        purpose=f"conversation-assurance:{external_case.case_id}",
        deadline_at="2026-08-30T12:00:00Z",
    )

    await runtime.evaluate(request, case_id=external_case.case_id)

    assert pantheon.fixed_assurance_facts is None


async def test_required_t2_failure_defers_campaign_assessment() -> None:
    runtime = RuntimePantheonConversationAssurance(
        pantheon=_HeldDeliberatingPantheon(),  # type: ignore[arg-type]
        coordinator=ConversationAssuranceCoordinator(
            ledger=InMemoryConversationAssuranceLedger(),
            reviewer=MixedFamilyAssuranceReviewer(
                first=_Evaluator("reviewer-a", "family-a"),
                second=_Evaluator("reviewer-b", "family-b"),
            ),
            rubric_version="1.0.0",
        ),
        source_revision="a" * 40,
        source_content_digest="b" * 64,
    )
    case = next(
        item
        for item in build_pantheon_census(PANTHEON_SPECS).cases
        if item.case_id == "t2-conflict-en"
    )
    request = SemanticTurnRequest(
        utterance=case.question,
        principal=SemanticTurnPrincipal(
            subject_id="operator-one",
            roles=(OperatorRole.READER,),
        ),
        session_id="pantheon-assurance:campaign-one",
        turn_id="turn-held",
        turn_sequence=0,
        locale=case.locale,
        purpose=f"conversation-assurance:{case.case_id}",
        deadline_at="2026-08-30T12:00:00Z",
    )

    result = await runtime.evaluate(request, case_id=case.case_id)

    assert result["assessment_state"] == "deferred"
    assert "required_t2_incomplete:budget_denied" in result["assessment_reasons"]


async def test_forbidden_t2_attempt_defers_campaign_assessment() -> None:
    runtime = RuntimePantheonConversationAssurance(
        pantheon=_DeliberatingPantheon(),  # type: ignore[arg-type]
        coordinator=ConversationAssuranceCoordinator(
            ledger=InMemoryConversationAssuranceLedger(),
            reviewer=MixedFamilyAssuranceReviewer(
                first=_Evaluator("reviewer-a", "family-a"),
                second=_Evaluator("reviewer-b", "family-b"),
            ),
            rubric_version="1.0.0",
        ),
        source_revision="a" * 40,
        source_content_digest="b" * 64,
    )
    case = next(
        item
        for item in build_pantheon_census(PANTHEON_SPECS).cases
        if item.case_id == "t2-consistent-en"
    )
    request = SemanticTurnRequest(
        utterance=case.question,
        principal=SemanticTurnPrincipal(
            subject_id="operator-one",
            roles=(OperatorRole.READER,),
        ),
        session_id="pantheon-assurance:campaign-one",
        turn_id="turn-forbidden",
        turn_sequence=0,
        locale=case.locale,
        purpose=f"conversation-assurance:{case.case_id}",
        deadline_at="2026-08-30T12:00:00Z",
    )

    result = await runtime.evaluate(request, case_id=case.case_id)

    assert result["assessment_state"] == "deferred"
    assert "forbidden_t2_attempted" in result["assessment_reasons"]


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


def test_runtime_corpus_requires_exact_digest_and_private_file(tmp_path) -> None:
    payload = {
        "schema_version": "1.0.0",
        "cases": [
            {
                "case_id": "external-one",
                "suite": "external",
                "locale": "en",
                "question": "Explain the verified external scenario.",
                "expected_primary_agent": "Odin",
                "expected_routing_method": "explicit",
                "allowed_contributors": [],
                "expected_handoff": False,
                "expected_handoff_owner": None,
                "t2_expectation": "forbidden",
            }
        ],
    }
    raw = json.dumps(payload)
    corpus = parse_pantheon_corpus(raw, PANTHEON_SPECS)
    path = tmp_path / "corpus.json"
    path.write_text(raw, encoding="utf-8")
    os.chmod(path, 0o600)
    environment = {
        "FDAI_CONVERSATION_ASSURANCE_CORPUS_FILE": str(path),
        "FDAI_CONVERSATION_ASSURANCE_CORPUS_DIGEST": corpus.content_digest,
    }

    loaded = runtime_assurance_corpus(environment)

    assert loaded is not None
    assert loaded.content_digest == corpus.content_digest
    with pytest.raises(RuntimeError, match="digest mismatch"):
        runtime_assurance_corpus(
            {
                **environment,
                "FDAI_CONVERSATION_ASSURANCE_CORPUS_DIGEST": "0" * 64,
            }
        )
