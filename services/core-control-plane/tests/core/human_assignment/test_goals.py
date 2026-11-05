from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

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


class _ConcurrentInvitationReadStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self._session_reads = 0
        self._both_sessions_read = asyncio.Event()

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        value = await super().read_state(key)
        if key.startswith("handover_goal:invitation:session:") and self._session_reads < 2:
            self._session_reads += 1
            if self._session_reads == 2:
                self._both_sessions_read.set()
            await self._both_sessions_read.wait()
        return value


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


async def test_goal_mutation_stops_after_assignment_leaves_active() -> None:
    service, store = await _service()
    goal = await _goal(service)
    degraded = replace(
        _assignment(),
        state=AssignmentState.DEGRADED,
        revision=8,
        degraded_reason="membership_revalidation_failed",
    )
    await store.write_state("human_assignment:case:case-1", degraded.to_dict())

    with pytest.raises(ValueError, match="active assignment"):
        await service.add_evidence(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            evidence=GoalEvidence("doc:document-1:version-1", "c" * 64, "document_span"),
            now=_NOW,
        )


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


async def test_concurrent_same_session_consumes_one_weekly_budget_slot() -> None:
    store = _ConcurrentInvitationReadStore()
    await store.write_state("human_assignment:case:case-1", _assignment().to_dict())
    service = HandoverGoalService(
        store=store,
        assignments=AssignmentCaseService(store),
        fatigue=HandoverFatiguePolicy(max_invitations_per_week=2),
    )
    await _goal(service)

    invitations = await asyncio.gather(
        service.invitation_for_session(
            subject_ref="subject-1", session_id="session-shared", now=_NOW
        ),
        service.invitation_for_session(
            subject_ref="subject-1", session_id="session-shared", now=_NOW
        ),
    )
    weekly = await store.read_states("handover_goal:week:", limit=1)

    assert sum(item is not None for item in invitations) == 1
    assert weekly[0]["count"] == 1
    assert len(weekly[0]["claimed_sessions"]) == 1


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
    with pytest.raises(ValueError, match="different content"):
        await service.add_evidence(
            goal_id=goal.goal_id,
            expected_revision=ready.revision,
            evidence=GoalEvidence("doc:document-1:version-1", "d" * 64, "document_span"),
            now=_NOW,
        )
    ready = await service.add_evidence(
        goal_id=goal.goal_id,
        expected_revision=ready.revision,
        evidence=GoalEvidence("doc:document-2:version-1", "d" * 64, "answer_span"),
        now=_NOW,
    )
    assert ready.state is HandoverGoalState.IN_PROGRESS
    with pytest.raises(ValueError, match="all six"):
        await service.accept(
            goal_id=goal.goal_id,
            expected_revision=ready.revision,
            now=_NOW,
        )
    with pytest.raises(ValueError, match="stale"):
        await service.decline(
            goal_id=goal.goal_id,
            expected_revision=snoozed.revision,
            now=_NOW,
        )


async def test_goals_model_service_and_require_current_evidence_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from fdai.core.human_assignment.goals import HandoverGoal, HandoverInvitation
    from fdai.core.rbac.resolver import Principal
    from fdai_service_contracts.handover_checklist import HANDOVER_SLOTS
    from tests.core.human_assignment.test_goal_acceptance import _ready

    # Model validations
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        GoalEvidence("doc:1:1", "BAD", "document_span")

    base_goal = HandoverGoal(
        goal_id="goal-1",
        assignment_case_id="case-1",
        subject_ref="subject-1",
        agent_name="Muninn",
        scope_ref="scope:platform",
        prompt_ref="prompt:1",
        priority=50,
        created_at=_NOW,
        not_applicable_reason_ref="reason:1",
    )
    for field_patch, match in [
        ({"agent_name": "UnknownAgent"}, "pantheon agent"),
        ({"priority": 0}, "priority MUST be in"),
        ({"revision": 0}, "revision MUST be positive"),
        ({"high_impact": "yes"}, "impact MUST be explicit"),
        (
            {"slot_exemptions": ((HANDOVER_SLOTS[0], "r1"), (HANDOVER_SLOTS[0], "r2"))},
            "distinct slots",
        ),
        ({"goal_id": "invalid space"}, "bounded safe reference"),
        ({"created_at": datetime(2026, 8, 3, 9, 0)}, "timezone-aware"),
    ]:
        with pytest.raises(ValueError, match=match):
            replace(base_goal, **field_patch)

    raw_goal = base_goal.to_dict()
    with pytest.raises(ValueError, match="evidence MUST be an array"):
        HandoverGoal.from_mapping({**raw_goal, "evidence": ()})
    with pytest.raises(ValueError, match="required slots do not match"):
        HandoverGoal.from_mapping({**raw_goal, "required_slots": tuple(HANDOVER_SLOTS)})

    with pytest.raises(ValueError, match="invitation_id MUST be non-empty"):
        HandoverInvitation("", "g", "Muninn", "p", "s", 3, 5)
    with pytest.raises(ValueError, match="pantheon agent"):
        HandoverInvitation("inv-1", "g", "BadAgent", "p", "s", 3, 5)

    # Service branches
    service, store = await _service()
    with pytest.raises(ValueError, match="outside the active assignment"):
        await service.create_goal(
            assignment_case_id="case-1",
            agent_name="Thor",
            scope_ref="scope:platform",
            prompt_ref="p:1",
            priority=50,
            now=_NOW,
        )

    goal = await _goal(service)
    # Replay create_goal returns existing; different priority with same identity raises conflict
    assert await _goal(service) == goal
    with pytest.raises(ValueError, match="bound to different content"):
        await _goal(service, priority=10)

    with pytest.raises(ValueError, match="not found"):
        await service.get_goal("missing-goal")

    # add_evidence replay, mark_not_applicable, decline replay, closed goal
    ev = GoalEvidence("doc:1:1", "c" * 64, "document_span", HANDOVER_SLOTS[0])
    g_ev = await service.add_evidence(
        goal_id=goal.goal_id, expected_revision=goal.revision, evidence=ev, now=_NOW
    )
    assert (
        await service.add_evidence(
            goal_id=goal.goal_id, expected_revision=g_ev.revision, evidence=ev, now=_NOW
        )
        == g_ev
    )
    with pytest.raises(ValueError, match="explicit handover slot"):
        await service.mark_not_applicable(
            goal_id=goal.goal_id,
            expected_revision=g_ev.revision,
            reason_ref="reason:na",
            slot=None,
            now=_NOW,
        )
    with pytest.raises(ValueError, match="already satisfied"):
        await service.mark_not_applicable(
            goal_id=goal.goal_id,
            expected_revision=g_ev.revision,
            reason_ref="reason:na",
            slot=HANDOVER_SLOTS[0],
            now=_NOW,
        )
    declined = await service.decline(
        goal_id=goal.goal_id, expected_revision=g_ev.revision, now=_NOW
    )
    assert (
        await service.decline(goal_id=goal.goal_id, expected_revision=g_ev.revision, now=_NOW)
        == declined
    )
    with pytest.raises(ValueError, match="closed to commands"):
        await service.snooze(goal_id=goal.goal_id, expected_revision=declined.revision, now=_NOW)

    # _claim_weekly_budget malformed state and CAS exhaustion
    service2, store2 = await _service()
    await _goal(service2)
    week = service2._fatigue.week_key(_NOW)
    from fdai.core.human_assignment.goals import _digest

    subj_hash = _digest("subject-1")
    week_key = f"handover_goal:week:{subj_hash}:{week}"
    await store2.write_state(week_key, {"revision": "bad", "count": 1})
    with pytest.raises(ValueError, match="fatigue state is malformed"):
        await service2.invitation_for_session(
            subject_ref="subject-1", session_id="s-malformed", now=_NOW
        )
    await store2.write_state(week_key, {"revision": 1, "count": 0, "claimed_sessions": []})
    orig_cas = store2.compare_and_set_state_with_audit
    monkeypatch.setattr(store2, "compare_and_set_state_with_audit", AsyncMock(return_value=False))
    assert (
        await service2.invitation_for_session(
            subject_ref="subject-1", session_id="s-cas-fail", now=_NOW
        )
        is None
    )
    monkeypatch.setattr(store2, "compare_and_set_state_with_audit", orig_cas)

    # require_current_evidence and accept edge branches
    acc_service, acc_store, admission, ready_goal = await _ready()
    acc_service._clock = lambda: _NOW
    await acc_service.require_current_evidence(ready_goal)

    # Accept stale revision
    with pytest.raises(ValueError, match="stale handover goal revision"):
        await acc_service.accept(
            goal_id=ready_goal.goal_id,
            expected_revision=999,
            principal=Principal("reviewer", frozenset({Role.OWNER})),
            now=_NOW,
        )

    owner_reviewed = await acc_service.accept(
        goal_id=ready_goal.goal_id,
        expected_revision=ready_goal.revision,
        principal=Principal("reviewer", frozenset({Role.OWNER})),
        now=_NOW,
    )
    backup_case = replace(
        _assignment(),
        case_id="backup-case",
        intent=replace(
            _assignment().intent,
            subject=ProviderSubject("entra", "reviewer"),
            duty_bindings=(DutyBinding("Muninn", Duty.BACKUP, "scope:platform"),),
        ),
    )
    await acc_store.write_state("human_assignment:case:backup-case", backup_case.to_dict())
    with pytest.raises(ValueError, match="two distinct people"):
        await acc_service.accept(
            goal_id=ready_goal.goal_id,
            expected_revision=owner_reviewed.revision,
            principal=Principal("reviewer", frozenset({Role.READER})),
            backup_case_id="backup-case",
            now=_NOW,
        )

    backup_case2 = replace(
        backup_case,
        intent=replace(backup_case.intent, subject=ProviderSubject("entra", "backup-user")),
    )
    await acc_store.write_state("human_assignment:case:backup-case", backup_case2.to_dict())
    with pytest.raises(ValueError, match="in the future"):
        await acc_service.accept(
            goal_id=ready_goal.goal_id,
            expected_revision=owner_reviewed.revision,
            principal=Principal("backup-user", frozenset({Role.READER})),
            backup_case_id="backup-case",
            now=_NOW - timedelta(minutes=1),
        )

    accepted_goal = await acc_service.accept(
        goal_id=ready_goal.goal_id,
        expected_revision=owner_reviewed.revision,
        principal=Principal("backup-user", frozenset({Role.READER})),
        backup_case_id="backup-case",
        now=_NOW,
    )
    await acc_service.require_current_evidence(accepted_goal)

    admission.available = False
    with pytest.raises(ValueError, match="reviewer eligibility is unavailable"):
        await acc_service.require_current_evidence(accepted_goal)
    admission.available = True

    with pytest.raises(ValueError, match="not eligible for source admission"):
        await acc_service.require_current_evidence(ready_goal)

    # Goal changes during source admission (2nd get_goal call)
    get_calls = 0
    orig_get_goal = acc_service.get_goal

    async def mutating_get_goal(gid: str) -> HandoverGoal:
        nonlocal get_calls
        get_calls += 1
        res = await orig_get_goal(gid)
        return replace(res, revision=res.revision + 1) if get_calls >= 2 else res

    monkeypatch.setattr(acc_service, "get_goal", mutating_get_goal)
    with pytest.raises(ValueError, match="changed during source admission"):
        await acc_service.require_current_evidence(accepted_goal)
    monkeypatch.setattr(acc_service, "get_goal", orig_get_goal)
