from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.human_assignment import (
    AssignmentCase,
    AssignmentCaseService,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    GoalEvidence,
    HandoverFatiguePolicy,
    HandoverGoalService,
    HandoverGoalState,
    ProviderSubject,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)


def _assignment(*, state: AssignmentState = AssignmentState.ACTIVE) -> AssignmentCase:
    receipts = (
        EffectReceipt(EffectKind.OWNERSHIP, "pr-1", "a" * 64, _NOW),
        EffectReceipt(EffectKind.IAM, "iam-1", "b" * 64, _NOW),
    )
    return AssignmentCase(
        case_id="case-1",
        intent=AssignmentIntent(
            idempotency_key="assignment-1",
            subject=ProviderSubject("entra", "subject-1"),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Muninn", Duty.PRIMARY, "scope:platform"),),
            goal_refs=("runbook-gaps-v1",),
            requester_ref="requester-1",
            justification="Collect cited operational knowledge for the assigned scope.",
        ),
        state=state,
        revision=7,
        effect_receipts=receipts if state is AssignmentState.ACTIVE else (),
    )


async def _service(
    *,
    policy: HandoverFatiguePolicy | None = None,
) -> tuple[HandoverGoalService, InMemoryStateStore]:
    store = InMemoryStateStore()
    await store.write_state("human_assignment:case:case-1", _assignment().to_dict())
    return (
        HandoverGoalService(
            store=store,
            assignments=AssignmentCaseService(store),
            fatigue=policy,
        ),
        store,
    )


async def _goal(service: HandoverGoalService, *, priority: int = 90):
    return await service.create_goal(
        assignment_case_id="case-1",
        agent_name="Muninn",
        scope_ref="scope:platform",
        prompt_ref="goal-template:runbook-gaps:v1",
        priority=priority,
        now=_NOW,
    )


async def test_goal_requires_active_matching_assignment() -> None:
    service, store = await _service()
    await store.write_state(
        "human_assignment:case:case-1",
        _assignment(state=AssignmentState.OWNERSHIP_MERGED).to_dict(),
    )

    with pytest.raises(ValueError, match="active assignment"):
        await _goal(service)


async def test_one_invitation_per_session_and_weekly_budget_survives_restart() -> None:
    service, store = await _service(policy=HandoverFatiguePolicy(max_invitations_per_week=2))
    await _goal(service)

    first = await service.invitation_for_session(
        subject_ref="subject-1", session_id="session-1", now=_NOW
    )
    duplicate = await service.invitation_for_session(
        subject_ref="subject-1", session_id="session-1", now=_NOW
    )
    second = await service.invitation_for_session(
        subject_ref="subject-1", session_id="session-2", now=_NOW
    )
    restarted = HandoverGoalService(
        store=store,
        assignments=AssignmentCaseService(store),
        fatigue=HandoverFatiguePolicy(max_invitations_per_week=2),
    )
    third = await restarted.invitation_for_session(
        subject_ref="subject-1", session_id="session-3", now=_NOW
    )

    assert first is not None and first.max_questions == 3 and first.max_minutes == 5
    assert duplicate is None
    assert second is not None
    assert third is None


async def test_concurrent_sessions_cannot_exceed_weekly_budget() -> None:
    service, _ = await _service(policy=HandoverFatiguePolicy(max_invitations_per_week=1))
    await _goal(service)

    invitations = await asyncio.gather(
        service.invitation_for_session(subject_ref="subject-1", session_id="session-a", now=_NOW),
        service.invitation_for_session(subject_ref="subject-1", session_id="session-b", now=_NOW),
    )

    assert sum(item is not None for item in invitations) == 1


async def test_incident_and_pending_approval_suppress_without_consuming_budget() -> None:
    service, _ = await _service()
    await _goal(service)

    assert (
        await service.invitation_for_session(
            subject_ref="subject-1",
            session_id="session-incident",
            incident_active=True,
            now=_NOW,
        )
        is None
    )
    assert (
        await service.invitation_for_session(
            subject_ref="subject-1",
            session_id="session-approval",
            approval_active=True,
            now=_NOW,
        )
        is None
    )
    assert (
        await service.invitation_for_session(
            subject_ref="subject-1", session_id="session-clear", now=_NOW
        )
        is not None
    )


async def test_snooze_decline_and_evidence_review_lifecycle() -> None:
    service, _ = await _service()
    goal = await _goal(service)
    snoozed = await service.snooze(
        goal_id=goal.goal_id,
        expected_revision=goal.revision,
        now=_NOW,
    )
    assert snoozed.snoozed_until == _NOW + timedelta(hours=24)
    assert (
        await service.invitation_for_session(
            subject_ref="subject-1", session_id="session-snoozed", now=_NOW
        )
        is None
    )
    with pytest.raises(ValueError, match="requires cited evidence"):
        await service.accept(
            goal_id=goal.goal_id,
            expected_revision=snoozed.revision,
            now=_NOW,
        )
    ready = await service.add_evidence(
        goal_id=goal.goal_id,
        expected_revision=snoozed.revision,
        evidence=GoalEvidence("doc:document-1:version-1", "c" * 64, "document_span"),
        now=_NOW,
    )
    ready = await service.add_evidence(
        goal_id=goal.goal_id,
        expected_revision=ready.revision,
        evidence=GoalEvidence("doc:document-2:version-1", "d" * 64, "answer_span"),
        now=_NOW,
    )
    accepted = await service.accept(
        goal_id=goal.goal_id,
        expected_revision=ready.revision,
        now=_NOW,
    )
    assert accepted.state is HandoverGoalState.ACCEPTED
    with pytest.raises(ValueError, match="stale"):
        await service.decline(
            goal_id=goal.goal_id,
            expected_revision=ready.revision,
            now=_NOW,
        )
