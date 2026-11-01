from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentModelError,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    ProviderSubject,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship.model import Duty

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def intent(*, role: Role = Role.READER, agent_name: str = "Odin") -> AssignmentIntent:
    return AssignmentIntent(
        idempotency_key="assignment-1",
        subject=ProviderSubject(provider="entra", subject_id="target-1"),
        requested_role=role,
        duty_bindings=(
            DutyBinding(agent_name=agent_name, duty=Duty.PRIMARY, scope_ref="scope:platform"),
        ),
        goal_refs=("goal:odin:operations:v1",),
        requester_ref="requester-1",
        justification="Assign platform ownership and bounded console access.",
    )


def effect(kind: EffectKind) -> EffectReceipt:
    return EffectReceipt(
        kind=kind,
        receipt_ref=f"receipt:{kind.value}:1",
        digest=f"digest-{kind.value}",
        received_at=NOW,
    )


def test_assignment_intent_is_immutable_and_round_trips() -> None:
    case = AssignmentCase(case_id="case-1", intent=intent())

    assert AssignmentCase.from_dict(case.to_dict()) == case
    with pytest.raises(FrozenInstanceError):
        case.intent.requester_ref = "other"  # type: ignore[misc]


def test_routine_assignment_rejects_break_glass_and_unknown_agents() -> None:
    with pytest.raises(AssignmentModelError, match="BreakGlass"):
        intent(role=Role.BREAK_GLASS)
    with pytest.raises(AssignmentModelError, match="unknown pantheon agent"):
        intent(agent_name="Unknown")


def test_active_case_requires_both_independent_effect_receipts() -> None:
    for receipts in ((), (effect(EffectKind.OWNERSHIP),), (effect(EffectKind.IAM),)):
        with pytest.raises(AssignmentModelError, match="ownership and IAM"):
            AssignmentCase(
                case_id="case-1",
                intent=intent(),
                state=AssignmentState.ACTIVE,
                effect_receipts=receipts,
            )

    active = AssignmentCase(
        case_id="case-1",
        intent=intent(),
        state=AssignmentState.ACTIVE,
        effect_receipts=(effect(EffectKind.OWNERSHIP), effect(EffectKind.IAM)),
    )

    assert active.has_required_effects


def test_human_assignment_hardening_rounds_h036_to_h065() -> None:
    from datetime import timedelta

    from fdai.core.human_assignment.audit import AssignmentAuditKind, build_assignment_audit
    from fdai.core.human_assignment.command_receipt import AssignmentCommandReceipt
    from fdai.core.human_assignment.coverage import (
        AssignmentCoverageError,
        required_review_quorum,
        validate_duty_bindings,
    )
    from fdai.core.human_assignment.fatigue import HandoverFatiguePolicy
    from fdai.core.human_assignment.goals import HandoverGoal, HandoverInvitation
    from fdai.core.human_assignment.ownership_coordination import (
        OwnershipProposal,
        VerifiedOwnershipMerge,
    )
    from fdai.core.human_assignment.repository import assignment_case_id
    from fdai.core.human_assignment.revocation_intent import AssignmentRevocation
    from fdai.core.human_assignment.scoped_duties import ScopedDutyPolicy, ScopedDutyValidationError
    from fdai.core.human_assignment.scoped_duty_ownership import ScopedDutyMergeObservation
    from fdai.core.human_assignment.transitions import (
        AssignmentTransitionError,
        StaleAssignmentRevisionError,
        TransitionIntent,
    )

    # H036-H037: control chars and case-insensitive duplicate goal_refs
    with pytest.raises(AssignmentModelError, match="control characters"):
        ProviderSubject(provider="entra", subject_id="bad\nvalue")
    with pytest.raises(AssignmentModelError, match="goal refs MUST be unique"):
        AssignmentIntent(
            idempotency_key="k1",
            subject=ProviderSubject(provider="entra", subject_id="target-1"),
            requested_role=Role.READER,
            duty_bindings=(
                DutyBinding(agent_name="Odin", duty=Duty.PRIMARY, scope_ref="scope:platform"),
            ),
            goal_refs=("goal:odin:v1", "GOAL:ODIN:V1"),
            requester_ref="req-1",
            justification="Assign ownership.",
        )

    # H038-H040: coverage, audit, command_receipt
    with pytest.raises(AssignmentCoverageError, match="at least one duty binding"):
        validate_duty_bindings(())
    with pytest.raises(AssignmentCoverageError, match="BreakGlass"):
        required_review_quorum(Role.BREAK_GLASS)
    case = AssignmentCase(case_id="case-1", intent=intent())
    with pytest.raises(ValueError, match="actor_ref MUST be non-empty"):
        build_assignment_audit(
            case, AssignmentAuditKind.REQUESTED, actor_ref=" ", timestamp=NOW.isoformat()
        )
    digest = "a" * 64
    receipt = AssignmentCommandReceipt.from_dict(
        {"proposal_id": f"operator-{digest[:32]}", "request_digest": digest}
    )
    assert receipt.request_digest == digest

    # H041-H043: fatigue bool check, goal slot_exemptions, invitation
    with pytest.raises(ValueError, match="MUST be in"):
        HandoverFatiguePolicy(max_invitations_per_session=True)
    with pytest.raises(ValueError, match="non-empty"):
        HandoverGoal(
            goal_id="g1",
            assignment_case_id="c1",
            subject_ref="s1",
            agent_name="Odin",
            scope_ref="scope:platform",
            prompt_ref="p1",
            priority=10,
            created_at=NOW,
            slot_exemptions=(("scope_exclusions", "   "),),
        )
    with pytest.raises(ValueError, match="positive integers"):
        HandoverInvitation(
            invitation_id="i1",
            goal_id="g1",
            agent_name="Odin",
            prompt_ref="p1",
            session_id="s1",
            max_questions=True,
            max_minutes=5,
        )

    # H049, H055, H058, H061, H062, H065
    with pytest.raises(ValueError, match="non-empty"):
        OwnershipProposal(case_id=" ", pr_ref="p1", candidate_digest=digest, opened_at=NOW)
    with pytest.raises(ValueError, match="non-empty"):
        VerifiedOwnershipMerge(pr_ref=" ", merge_commit_sha="s1", merged_yaml="y1", merged_at=NOW)
    with pytest.raises(ValueError, match="non-empty"):
        assignment_case_id("req-1", "   ")
    with pytest.raises(ValueError, match="bounded exact text"):
        AssignmentRevocation(case_id="bad\ncase", revision=1, replacement_revisions={"c2": 1})
    with pytest.raises(StaleAssignmentRevisionError, match="stale"):
        TransitionIntent(expected_revision=True, target_state=AssignmentState.PENDING_REVIEW)
    with pytest.raises(AssignmentTransitionError, match="AssignmentState"):
        TransitionIntent(expected_revision=1, target_state="pending_review")  # type: ignore[arg-type]
    with pytest.raises(ScopedDutyValidationError, match="finite"):
        ScopedDutyPolicy(
            max_resolution_age=timedelta(minutes=5),
            read_timeout_seconds=float("nan"),
            total_timeout_seconds=10.0,
        )
    with pytest.raises(ValueError, match="MUST not invert"):
        ScopedDutyMergeObservation(
            pr_ref="pr1",
            path="config/scoped-duty-plans/1.json",
            candidate_digest=digest,
            merge_commit_sha="b" * 40,
            observed_at=NOW + timedelta(minutes=5),
            expires_at=NOW,
        )
