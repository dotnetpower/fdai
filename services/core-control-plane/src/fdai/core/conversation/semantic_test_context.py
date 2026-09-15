"""Compile source-grounded semantic meaning into an inert test-context proposal."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticDiscourseMode,
    SemanticJudgmentDisposition,
)
from fdai_service_contracts.test_context import (
    TestContextDraft,
    TestContextRequest,
    TestContextWindow,
)

from .semantic_judgment import SemanticJudgmentObservation, SemanticJudgmentResult

if TYPE_CHECKING:
    from .semantic_planning_models import SemanticPlanningOutcome

TEST_CONTEXT_INTENT = "create.test_context"
_FIELDS = frozenset(
    {
        "target_ref",
        "signal_code",
        "expected_min",
        "expected_max",
        "effective_from",
        "effective_to",
    }
)


def test_context_capability() -> dict[str, object]:
    """Describe the bounded draft capability without granting any shared policy authority."""
    return {
        "kind": "governance_proposal",
        "name": TEST_CONTEXT_INTENT,
        "action_subject": "Change",
        "action_posture": "draft_only",
        "required_source_targets": sorted(_FIELDS),
        "description": (
            "Propose expected test signals, never an exemption or approval. "
            "Use distinct exact utterance spans and offset-aware ISO timestamps. "
            "Unresolved targets, ranges, or relative times require clarification."
        ),
        "execution_authority": False,
    }


def test_context_planning_outcome(
    *,
    judgment: SemanticJudgmentResult,
    utterance: str,
    locale: str,
    observations: tuple[SemanticJudgmentObservation, ...],
) -> SemanticPlanningOutcome | None:
    """Route only context-proposal meaning; all other planning remains unchanged."""
    from .semantic_planning_models import SemanticPlanningDisposition, SemanticPlanningOutcome

    if judgment.proposal is None or judgment.proposal.primary_intent != TEST_CONTEXT_INTENT:
        return None
    try:
        draft = test_context_draft_from_judgment(
            judgment=judgment,
            utterance=utterance,
            source_ref="semantic-judgment:" + judgment.receipt.receipt_digest,
        )
    except ValueError:
        return SemanticPlanningOutcome(
            disposition=SemanticPlanningDisposition.CLARIFICATION,
            reason="test_context_proposal_incomplete",
            clarification=(
                "대상, 신호, 예상 상하한과 시간대가 포함된 "
                "시작 및 종료 시각을 명확히 지정해 주시겠어요?"
                if locale.casefold().startswith("ko")
                else "Which exact target, signal, expected limits, and "
                "offset-aware start and end times should the proposal use?"
            ),
            model_observations=observations + judgment.observations,
        )
    return SemanticPlanningOutcome(
        disposition=SemanticPlanningDisposition.ACTION_DRAFT,
        reason="test_context_proposal_requires_scope_and_review",
        test_context_draft=draft,
        model_observations=observations + judgment.observations,
    )


def test_context_request_from_judgment(
    *,
    judgment: SemanticJudgmentResult,
    utterance: str,
    access_scope_digest: str,
    policy_revision: str,
    source_ref: str,
) -> TestContextRequest:
    """Bind an inert source-grounded draft to a selected scope and policy for later review."""
    draft = test_context_draft_from_judgment(
        judgment=judgment,
        utterance=utterance,
        source_ref=source_ref,
    )
    identity = content_digest(
        {
            "source_ref": source_ref,
            "scope_digest": access_scope_digest,
            "semantic_receipt": draft.semantic_receipt,
        }
    )
    return TestContextRequest(
        operation="propose",
        context_id="test-context:" + identity.removeprefix("sha256:"),
        access_scope_digest=access_scope_digest,
        policy_revision=policy_revision,
        target_ref=draft.target_ref,
        signal_code=draft.signal_code,
        expected_revision=0,
        source_ref=draft.source_ref,
        semantic_receipt=draft.semantic_receipt,
        **draft.window.model_dump(),
    )


def test_context_draft_from_judgment(
    *,
    judgment: SemanticJudgmentResult,
    utterance: str,
    source_ref: str,
) -> TestContextDraft:
    """Build a proposal only; server scope and later independent review remain mandatory.

    Every value must be an exact source span in this utterance. Unresolved relative time,
    missing fields, quoted/hypothetical meaning, or an unaccepted judgment requires clarification.
    The returned record carries neither a human identity nor approval or execution authority.
    """
    proposal = judgment.proposal
    receipt = judgment.receipt
    if (
        proposal is None
        or receipt.disposition is not SemanticJudgmentDisposition.ACCEPTED
        or receipt.input_digest != content_digest({"utterance": utterance})
        or receipt.proposal_digest != content_digest(proposal.model_dump(mode="json"))
        or receipt.ambiguous
        or proposal.ambiguous
        or proposal.discourse_mode is not SemanticDiscourseMode.DIRECT
        or proposal.primary_intent != TEST_CONTEXT_INTENT
        or proposal.action_subject != "Change"
        or proposal.action_posture != "draft_only"
        or proposal.secondary_intents
        or proposal.forbidden_actions
    ):
        raise ValueError("test context requires one accepted direct proposal judgment")
    values: dict[str, str] = {}
    spans: list[tuple[int, int]] = []
    for target in proposal.targets:
        if (
            target.kind not in _FIELDS
            or target.kind in values
            or target.canonical_value is not None
            or target.source_end > len(utterance)
            or utterance[target.source_start : target.source_end] != target.value
            or any(target.source_start < end and start < target.source_end for start, end in spans)
        ):
            raise ValueError("test context values require distinct exact source spans")
        values[target.kind] = target.value
        spans.append((target.source_start, target.source_end))
    if set(values) != _FIELDS:
        raise ValueError("test context requires target, signal, range, and explicit time bounds")
    try:
        return TestContextDraft(
            target_ref=values["target_ref"],
            signal_code=values["signal_code"],
            source_ref=source_ref,
            semantic_receipt=receipt.receipt_digest,
            window=TestContextWindow(
                expected_min=float(values["expected_min"]),
                expected_max=float(values["expected_max"]),
                effective_from=datetime.fromisoformat(values["effective_from"]),
                effective_to=datetime.fromisoformat(values["effective_to"]),
            ),
        )
    except (ValueError, OverflowError) as exc:
        raise ValueError("test context range or explicit timestamp requires clarification") from exc
