"""Core acceptance requires six slots, human separation, and current source admission."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.human_assignment import (
    AssignmentCaseService,
    DutyBinding,
    GoalEvidence,
    HandoverGoalService,
    HandoverGoalState,
    ProviderSubject,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai_service_contracts.handover_checklist import HANDOVER_SLOTS
from tests.core.human_assignment.test_goals import _NOW, _assignment, _goal, _service


class Admission:
    def __init__(self):
        self.available = True
        self.reviewers = []

    async def verify_subject(self, *, subject_ref, assignment_case_id):
        return self.available

    async def verify(self, *, subject_ref, evidence_ref, digest, reviewer_ref):
        self.reviewers.append(reviewer_ref)
        return self.available

    async def may_review(self, *, reviewer_ref, agent_name, scope_ref, role):
        return self.available


async def _ready():
    _, store = await _service()
    admission = Admission()
    service = HandoverGoalService(
        store=store,
        assignments=AssignmentCaseService(store),
        evidence_admission=admission,
        review_eligibility=admission,
    )
    goal = await _goal(service)
    for slot in HANDOVER_SLOTS:
        goal = await service.add_evidence(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            evidence=GoalEvidence("doc:example:v1", "a" * 64, "document_span", slot),
            now=_NOW,
        )
    return service, store, admission, goal


async def test_current_independent_owner_and_backup_can_accept_only_complete_evidence():
    service, store, admission, goal = await _ready()
    assert goal.state is HandoverGoalState.READY_FOR_REVIEW
    reviewed = await service.accept(
        goal_id=goal.goal_id,
        expected_revision=goal.revision,
        principal=Principal("reviewer", frozenset({Role.OWNER})),
        now=_NOW,
    )
    assert reviewed.state is HandoverGoalState.READY_FOR_REVIEW
    backup = replace(
        _assignment(),
        case_id="backup",
        intent=replace(
            _assignment().intent,
            subject=ProviderSubject("entra", "backup-person"),
            duty_bindings=(DutyBinding("Muninn", Duty.BACKUP, "scope:platform"),),
        ),
    )
    await store.write_state("human_assignment:case:backup", backup.to_dict())
    accepted = await service.accept(
        goal_id=goal.goal_id,
        expected_revision=reviewed.revision,
        principal=Principal("backup-person", frozenset({Role.READER})),
        backup_case_id="backup",
        now=_NOW,
    )
    assert accepted.state is HandoverGoalState.ACCEPTED
    assert set(admission.reviewers) == {"reviewer", "backup-person"}


@pytest.mark.parametrize(
    "principal",
    [
        None,
        Principal("subject-1", frozenset({Role.OWNER})),
        Principal("reviewer", frozenset({Role.READER})),
    ],
)
async def test_unauthenticated_self_or_wrong_role_cannot_accept(principal):
    service, _, _, goal = await _ready()
    with pytest.raises(ValueError, match="independent"):
        await service.accept(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            principal=principal,
            now=_NOW,
        )


async def test_stale_or_unavailable_document_admission_prevents_acceptance():
    service, store, admission, goal = await _ready()
    admission.available = False
    owner = Principal("reviewer", frozenset({Role.OWNER}))
    for checked in (
        service,
        HandoverGoalService(store=store, assignments=AssignmentCaseService(store)),
    ):
        with pytest.raises(ValueError, match="admission"):
            await checked.accept(
                goal_id=goal.goal_id,
                expected_revision=goal.revision,
                principal=owner,
                now=_NOW,
            )
    assert (await service.get_goal(goal.goal_id)).owner_review is None


async def test_unbound_current_reviewer_eligibility_cannot_record_acceptance():
    _, store, admission, goal = await _ready()
    unbound = HandoverGoalService(
        store=store,
        assignments=AssignmentCaseService(store),
        evidence_admission=admission,
    )
    with pytest.raises(ValueError, match="reviewer eligibility"):
        await unbound.accept(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            principal=Principal("reviewer", frozenset({Role.OWNER})),
            now=_NOW,
        )


async def test_goal_creation_replays_fixed_intent_without_sliding_created_time():
    service, _ = await _service()
    first = await _goal(service)
    second = await service.create_goal(
        assignment_case_id=first.assignment_case_id,
        agent_name=first.agent_name,
        scope_ref=first.scope_ref,
        prompt_ref=first.prompt_ref,
        priority=first.priority,
        now=_NOW + timedelta(minutes=1),
    )
    assert second == first


async def test_one_global_not_applicable_reason_cannot_complete_all_slots():
    service, _ = await _service()
    goal = await _goal(service)
    with pytest.raises(ValueError, match="explicit.*slot"):
        await service.mark_not_applicable(
            goal_id=goal.goal_id,
            expected_revision=1,
            reason_ref="reason:excluded",
            now=_NOW,
        )
    for slot in HANDOVER_SLOTS:
        goal = await service.mark_not_applicable(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            reason_ref="reason:excluded",
            slot=slot,
            now=_NOW,
        )
    assert goal.state is HandoverGoalState.READY_FOR_REVIEW


async def test_same_reference_replay_revalidates_assignment_after_revocation():
    service, store, _, goal = await _ready()
    old = _assignment()
    await store.write_state(
        "human_assignment:case:case-1",
        replace(
            old,
            state=type(old.state).DEGRADED,
            revision=8,
            degraded_reason="revocation_pending",
        ).to_dict(),
    )
    with pytest.raises(ValueError, match="active assignment"):
        await service.add_evidence(
            goal_id=goal.goal_id,
            expected_revision=1,
            evidence=goal.evidence[0],
            now=_NOW,
        )


@pytest.mark.parametrize(
    "roles,provider",
    [
        (frozenset(), "entra"),
        (frozenset({Role.BREAK_GLASS}), "entra"),
        (frozenset({Role.READER}), "other"),
    ],
)
async def test_backup_case_never_substitutes_for_current_ordinary_human_role(roles, provider):
    service, store, _, goal = await _ready()
    backup = replace(
        _assignment(),
        case_id="backup",
        intent=replace(
            _assignment().intent,
            subject=ProviderSubject(provider, "backup-person"),
            duty_bindings=(DutyBinding("Muninn", Duty.BACKUP, "scope:platform"),),
        ),
    )
    await store.write_state("human_assignment:case:backup", backup.to_dict())
    with pytest.raises(ValueError, match="backup"):
        await service.accept(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            principal=Principal("backup-person", roles),
            backup_case_id="backup",
            now=_NOW,
        )


async def test_prior_backup_document_acl_is_rechecked_before_final_owner(monkeypatch):
    service, store, admission, goal = await _ready()
    backup = replace(
        _assignment(),
        case_id="backup",
        intent=replace(
            _assignment().intent,
            subject=ProviderSubject("entra", "backup-person"),
            duty_bindings=(DutyBinding("Muninn", Duty.BACKUP, "scope:platform"),),
        ),
    )
    await store.write_state("human_assignment:case:backup", backup.to_dict())
    reviewed = await service.accept(
        goal_id=goal.goal_id,
        expected_revision=goal.revision,
        principal=Principal("backup-person", frozenset({Role.READER})),
        backup_case_id="backup",
        now=_NOW,
    )

    async def lost_backup_access(*, reviewer_ref, **kwargs):
        return reviewer_ref != "backup-person"

    monkeypatch.setattr(admission, "verify", lost_backup_access)
    with pytest.raises(ValueError, match="admission"):
        await service.accept(
            goal_id=goal.goal_id,
            expected_revision=reviewed.revision,
            principal=Principal("reviewer", frozenset({Role.OWNER})),
            now=_NOW,
        )
    assert (await service.get_goal(goal.goal_id)).state is HandoverGoalState.READY_FOR_REVIEW


async def test_all_exemptions_do_not_bypass_current_subject_admission(monkeypatch):
    service, store, admission, goal = await _ready()
    exempt = replace(
        goal,
        evidence=(),
        slot_exemptions=tuple((slot, "reason:excluded") for slot in HANDOVER_SLOTS),
    )
    await store.write_state("handover_goal:goal:" + goal.goal_id, exempt.to_dict())

    async def unavailable_subject(**kwargs):
        return False

    monkeypatch.setattr(admission, "verify_subject", unavailable_subject)
    with pytest.raises(ValueError, match="admission"):
        await service.accept(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            principal=Principal("reviewer", frozenset({Role.OWNER})),
            now=_NOW,
        )
    assert (await service.get_goal(goal.goal_id)).owner_review is None


async def test_long_review_io_cannot_commit_with_an_old_supplied_time(monkeypatch):
    service, _, admission, goal = await _ready()
    clock = {"at": _NOW}
    monkeypatch.setattr(service, "_clock", lambda: clock["at"], raising=False)

    async def slow_roles(**kwargs):
        clock["at"] += timedelta(minutes=6)
        return True

    monkeypatch.setattr(admission, "may_review", slow_roles)
    with pytest.raises(ValueError, match="window"):
        await service.accept(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            principal=Principal("reviewer", frozenset({Role.OWNER})),
            now=_NOW,
        )
    assert (await service.get_goal(goal.goal_id)).owner_review is None
