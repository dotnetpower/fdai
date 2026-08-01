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
