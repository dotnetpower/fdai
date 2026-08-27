from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fdai.core.conversation.answer_planning import (
    AnswerContribution,
    AnswerPlanningConfig,
    AnswerPlanningResult,
    GroundedFact,
    PlanningStatus,
)
from fdai.core.conversation_assurance.quality_orchestration_observations import (
    HandoffScenarioResult,
    PlanningOrchestrationScenarioResult,
    observe_handoff,
    observe_planning_orchestration,
)
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    ProviderSubject,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship.model import Duty

_EVIDENCE = "a" * 64


def _planning(*, conflicts: tuple[str, ...] = ()) -> AnswerPlanningResult:
    contribution = AnswerContribution(
        agent="Mimir",
        facts=(GroundedFact("Fact.", "evidence-1"),),
        caveats=(),
        suggested_sections=(),
        evidence_refs=("evidence-1",),
        confidence=0.9,
    )
    return AnswerPlanningResult(
        status=PlanningStatus.COMPLETED if not conflicts else PlanningStatus.DEGRADED,
        primary_agent="Bragi",
        consulted_agents=("Mimir",),
        contributions=(contribution,),
        failures=(),
        elapsed_ms=100,
        unique_evidence_count=1,
        duplicate_evidence_count=0,
        conflicting_evidence_refs=conflicts,
        covered_sections=(),
        estimated_added_tokens=20,
        budget=AnswerPlanningConfig(),
    )


def _handoff(state: AssignmentState) -> AssignmentCase:
    intent = AssignmentIntent(
        idempotency_key="key-1",
        subject=ProviderSubject("entra", "subject-1"),
        requested_role=Role.READER,
        duty_bindings=(DutyBinding("Odin", Duty.PRIMARY, "scope-1"),),
        goal_refs=(),
        requester_ref="requester-1",
        justification="Assign an accountable owner.",
    )
    receipts = (
        EffectReceipt(
            EffectKind.OWNERSHIP, "ownership-1", "digest-1", datetime(2026, 8, 27, tzinfo=UTC)
        ),
        EffectReceipt(EffectKind.IAM, "iam-1", "digest-2", datetime(2026, 8, 27, tzinfo=UTC)),
    )
    return AssignmentCase(
        case_id="assignment-1",
        intent=intent,
        state=state,
        effect_receipts=receipts,
    )


def test_planning_result_measures_owner_fanout_attribution_and_conflicts() -> None:
    actual = _planning(conflicts=("evidence-conflict",))
    contributions = observe_planning_orchestration(
        PlanningOrchestrationScenarioResult(
            "case-1",
            "Bragi",
            PlanningStatus.DEGRADED,
            ("Mimir",),
            (hashlib.sha256(b"evidence-conflict").hexdigest(),),
            actual,
            _EVIDENCE,
        )
    )
    assert [item.item_id for item in contributions] == [31, 32, 33, 34]
    assert all(item.value == 1.0 for item in contributions)


def test_planning_mismatches_score_zero_without_hiding_other_results() -> None:
    contributions = observe_planning_orchestration(
        PlanningOrchestrationScenarioResult(
            "case-1",
            "Odin",
            PlanningStatus.TIMED_OUT,
            ("Odin",),
            (),
            _planning(),
            _EVIDENCE,
        )
    )
    assert [item.value for item in contributions] == [0.0, 0.0, 0.0, 1.0]


def test_handoff_requires_expected_state_and_both_effects() -> None:
    matching = observe_handoff(
        HandoffScenarioResult(
            "case-1",
            AssignmentState.ACTIVE,
            True,
            _handoff(AssignmentState.ACTIVE),
            _EVIDENCE,
        )
    )
    mismatch = observe_handoff(
        HandoffScenarioResult(
            "case-2",
            AssignmentState.PENDING_REVIEW,
            False,
            _handoff(AssignmentState.ACTIVE),
            _EVIDENCE,
        )
    )
    assert matching.item_id == 35
    assert matching.value == 1.0
    assert mismatch.value == 0.0
