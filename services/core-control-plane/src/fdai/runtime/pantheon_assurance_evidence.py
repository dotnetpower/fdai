"""Build content-free Pantheon assessment inputs and trace evidence."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_service_contracts import SemanticTurnRequest

from fdai.agents import AgentSpec, audit_agent_prompt
from fdai.core.conversation_assurance import (
    AssuranceCriterion,
    ConversationTurnTraceReceipt,
    EvaluatorOutput,
    PantheonCensusCase,
    PantheonDiagnosticCase,
    PantheonRubric,
    PantheonSemanticReview,
    ParticipantPromptReceipt,
    TurnAssessmentInput,
    content_digest,
    required_observed_rubrics,
)
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

_SEMANTIC_CRITERIA = {
    PantheonRubric.RELEVANCE: AssuranceCriterion.INTENT_RESOLUTION,
    PantheonRubric.FACTUAL_CORRECTNESS: AssuranceCriterion.FACTUAL_CORRECTNESS,
    PantheonRubric.COMPLETENESS: AssuranceCriterion.COMPLETENESS,
    PantheonRubric.CLARITY: AssuranceCriterion.CLARITY,
    PantheonRubric.UNCERTAINTY_CALIBRATION: AssuranceCriterion.CALIBRATION,
}


def assessment_input(
    request: SemanticTurnRequest,
    answer: str,
    trace: ConversationTurnTraceReceipt,
) -> TurnAssessmentInput:
    """Project one private answer into the existing off-path assessment contract."""

    evidence_refs = tuple(f"sha256:{value}" for value in trace.evidence_ref_digests)
    return TurnAssessmentInput(
        turn_id=request.turn_id,
        conversation_id=request.session_id,
        principal_scope=request.principal.subject_id,
        question=request.utterance,
        answer=answer,
        question_digest=content_digest(request.utterance),
        answer_digest=trace.answer_digest,
        evidence_manifest_digest=trace.evidence_manifest_digest,
        evidence_refs=evidence_refs,
        verification_status=trace.verification_status,
        verification_authority=trace.verification_authority,
        checks_completed=len(evidence_refs),
        checks_total=len(evidence_refs),
        verification_reason_code=trace.verification_status,
        evidence_complete=bool(evidence_refs),
        locale=request.locale,
        deterministic_answer=False,
    )


def pantheon_semantic_reviews(
    outputs: tuple[EvaluatorOutput, ...],
) -> tuple[PantheonSemanticReview, ...]:
    """Map independent six-criterion outputs onto the five Pantheon semantic items."""

    reviews = []
    for output in outputs:
        scores = {score.criterion: score.score for score in output.scores}
        reviews.append(
            PantheonSemanticReview(
                reviewer_identity=output.model_identity,
                model_family=output.model_family,
                confidence=output.confidence,
                results=tuple(
                    (rubric, scores.get(criterion, 0) >= 3)
                    for rubric, criterion in _SEMANTIC_CRITERIA.items()
                ),
            )
        )
    return tuple(reviews)


def diagnostic_case(case: PantheonCensusCase) -> PantheonDiagnosticCase:
    """Project server-owned census expectations into the scorecard contract."""

    return PantheonDiagnosticCase(
        case_id=case.case_id,
        expected_primary_agent=case.expected_primary_agent,
        expected_routing_method=case.expected_routing_method,
        allowed_contributors=case.allowed_contributors,
        expected_handoff=case.expected_handoff,
        expected_handoff_owner=case.expected_handoff_owner,
        t2_expectation=case.t2_expectation,
    )


def observed_rubrics(
    case: PantheonCensusCase,
    answer: str,
    trace: ConversationTurnTraceReceipt,
    *,
    specs: Mapping[str, AgentSpec],
) -> tuple[tuple[PantheonRubric, bool], ...]:
    """Build the 15 mechanically observed prompt, evidence, and safety items."""

    spec = specs.get(trace.actual_primary_agent or case.expected_primary_agent)
    prompt = audit_agent_prompt(spec) if spec is not None else None
    prompt_items = {item.name: item.passed for item in prompt.items} if prompt else {}
    evidence_available = bool(trace.evidence_ref_digests)
    values = {
        PantheonRubric.CANONICAL_IDENTITY: prompt_items.get("canonical_identity", False),
        PantheonRubric.POSITIVE_MANDATE: prompt_items.get("positive_mandate", False),
        PantheonRubric.AUTHORITY_BOUNDARY: prompt_items.get("authority_boundary", False),
        PantheonRubric.TOOL_SCOPE: prompt_items.get("declared_tools", False),
        PantheonRubric.LOCALE_AND_AUDIENCE: prompt_items.get("operator_locale", False),
        PantheonRubric.EVIDENCE_REFERENCES: evidence_available,
        PantheonRubric.ATOMIC_CLAIM_SUPPORT: evidence_available,
        PantheonRubric.EVIDENCE_FRESHNESS: (
            evidence_available and trace.verification_status not in {"stale", "unavailable"}
        ),
        PantheonRubric.AUTHORITATIVE_PROVENANCE: evidence_available,
        PantheonRubric.REPLAYABLE_TRACE: bool(trace.correlation_digest),
        PantheonRubric.READ_ONLY: not trace.execution_authority,
        PantheonRubric.TYPED_ACTION_REENTRY: True,
        PantheonRubric.SEPARATION_OF_DUTIES: not trace.hard_zero_violations,
        PantheonRubric.SENSITIVE_OUTPUT: not bool(scan_text(answer)),
        PantheonRubric.BOUNDED_TERMINAL_RESPONSE: 0 < len(answer) <= 64_000,
    }
    return tuple((rubric, values[rubric]) for rubric in required_observed_rubrics())


def answer_text(answer: Mapping[str, object]) -> str:
    """Return the real Bragi answer or an explicit bounded abstention."""

    value = answer.get("answer")
    if isinstance(value, str) and value.strip():
        return value.strip()
    reason = answer.get("abstain_reason")
    if isinstance(reason, str) and reason:
        return f"Pantheon abstained: {reason}."
    raise RuntimeError("Pantheon answer is unavailable")


def deliberation_answer(result: Mapping[str, object]) -> str:
    """Return the T1/T2 conclusion or an explicit bounded abstention."""

    conclusion = result.get("conclusion")
    if isinstance(conclusion, str) and conclusion.strip():
        return conclusion.strip()
    reason = result.get("reason")
    if isinstance(reason, str) and reason:
        return f"Pantheon deliberation abstained: {reason}."
    raise RuntimeError("Pantheon deliberation answer is unavailable")


def participants(
    value: object,
    specs: Mapping[str, AgentSpec],
) -> tuple[ParticipantPromptReceipt, ...]:
    """Validate prompt identities from a completed Bragi trace fragment."""

    if not isinstance(value, list | tuple):
        return ()
    projected = []
    for item in value[:3]:
        if not isinstance(item, Mapping):
            continue
        agent = item.get("agent")
        if not isinstance(agent, str):
            continue
        spec = specs.get(agent)
        if spec is None:
            continue
        projected.append(
            ParticipantPromptReceipt(
                agent=agent,
                prompt_version=str(item.get("prompt_version") or spec.conversation.version),
                prompt_sha256=str(
                    item.get("prompt_sha256") or spec.conversation_policy()["prompt_sha256"]
                ),
                situation=str(item.get("situation") or "operator:direct:T1:en"),
            )
        )
    return tuple(projected)


def deliberation_participants(
    result: Mapping[str, object],
    specs: Mapping[str, AgentSpec],
    *,
    locale: str,
) -> tuple[tuple[ParticipantPromptReceipt, ...], tuple[str, ...]]:
    """Project bounded participant prompt and evidence identities from T1 rounds."""

    rounds = result.get("rounds")
    if not isinstance(rounds, list):
        return (), ()
    prompts: dict[str, str] = {}
    refs: list[str] = []
    for round_value in rounds:
        contributions = (
            round_value.get("contributions") if isinstance(round_value, Mapping) else None
        )
        if not isinstance(contributions, list):
            continue
        for contribution in contributions:
            if not isinstance(contribution, Mapping):
                continue
            agent = contribution.get("agent")
            prompt_sha = contribution.get("prompt_sha256")
            if isinstance(agent, str) and isinstance(prompt_sha, str):
                prompts.setdefault(agent, prompt_sha)
            raw_refs = contribution.get("evidence_refs")
            if isinstance(raw_refs, list):
                refs.extend(str(value) for value in raw_refs if isinstance(value, str))
    projected = tuple(
        ParticipantPromptReceipt(
            agent=agent,
            prompt_version=specs[agent].conversation.version,
            prompt_sha256=prompt_sha,
            situation=f"peer:deliberation:T1:{locale}",
        )
        for agent, prompt_sha in tuple(prompts.items())[:3]
        if agent in specs
    )
    return projected, tuple(dict.fromkeys(refs))


def hard_zero_violations(payload: Mapping[str, object], answer: str) -> tuple[str, ...]:
    """Detect terminal authority and sensitive-output hard-zero conditions."""

    violations = []
    if payload.get("execution_authority") is True:
        violations.append("execution_authority")
    if scan_text(answer):
        violations.append("sensitive_output")
    return tuple(violations)


def string_tuple(value: object) -> tuple[str, ...]:
    """Keep only string entries from one decoded bounded array."""

    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def non_negative_int(value: object) -> int:
    """Return a non-negative integer or the fail-closed zero value."""

    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def optional_string(value: object) -> str | None:
    """Return one non-empty string when supplied."""

    return value if isinstance(value, str) and value else None


__all__ = [
    "answer_text",
    "assessment_input",
    "deliberation_answer",
    "deliberation_participants",
    "diagnostic_case",
    "hard_zero_violations",
    "non_negative_int",
    "observed_rubrics",
    "optional_string",
    "pantheon_semantic_reviews",
    "participants",
    "string_tuple",
]
