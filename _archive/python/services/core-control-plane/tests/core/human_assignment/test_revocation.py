"""Synthetic reverse-order coordination; these tests grant no provider authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

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
    HandoverGoalService,
    ProviderSubject,
    ReviewDecision,
    ReviewReceipt,
)
from fdai.core.human_assignment.revocation_intent import AssignmentRevocation
from fdai.core.human_assignment.transitions import (
    AssignmentTransitionError,
    TransitionIntent,
    validate_transition,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 9, 14, tzinfo=UTC)
OLD_SUBJECT = "00000000-0000-0000-0000-000000000010"


def _owner(oid="human:requester"):
    return Principal(oid=oid, roles=frozenset({Role.OWNER}))


def _effect(kind):
    return EffectReceipt(kind, f"synthetic:{kind.value}:removed", "b" * 64, NOW)


def _old():
    return AssignmentCase(
        case_id="old",
        intent=AssignmentIntent(
            idempotency_key="old",
            subject=ProviderSubject("entra", OLD_SUBJECT),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Thor", Duty.PRIMARY, "scope:platform"),),
            goal_refs=(),
            requester_ref="human:original-requester",
            justification="Synthetic original grant.",
        ),
        state=AssignmentState.ACTIVE,
        revision=7,
        reviews=(ReviewReceipt("human:original-reviewer", ReviewDecision.APPROVE, NOW),),
        effect_receipts=(_effect(EffectKind.OWNERSHIP), _effect(EffectKind.IAM)),
    )


def _intent(key="remove"):
    return replace(
        _old().intent,
        idempotency_key=key,
        requester_ref="human:requester",
        justification="Review exact replacement coverage before removing this assignment.",
        revocation=AssignmentRevocation("old", 7, {"primary": 7, "backup": 7}),
    )


async def _cases(store=None):
    store = store or InMemoryStateStore()
    await store.write_state("human_assignment:case:old", _old().to_dict())
    return AssignmentCaseService(store)


async def _reviewed(cases, key="remove"):
    draft = await cases.create_case(principal=_owner(), intent=_intent(key), now=NOW)
    pending = await cases.submit_for_review(
        principal=_owner(), case_id=draft.case_id, expected_revision=draft.revision, now=NOW
    )
    return await cases.review(
        principal=_owner("human:reviewer"),
        case_id=pending.case_id,
        expected_revision=pending.revision,
        decision=ReviewDecision.APPROVE,
        now=NOW,
    )


async def _removed(cases):
    approved = await _reviewed(cases)
    applying = await cases.begin_iam_apply(
        case_id=approved.case_id, expected_revision=approved.revision, actor_ref="Thor", now=NOW
    )
    return await cases.record_effect(
        case_id=applying.case_id,
        expected_revision=applying.revision,
        receipt=_effect(EffectKind.IAM),
        actor_ref="Thor",
    )


@pytest.mark.parametrize("revision", [True, False, 0, -1, "7", 7.0])
def test_revocation_references_never_coerce_revisions(revision):
    with pytest.raises(ValueError, match="revision"):
        AssignmentRevocation("old", revision, {"primary": 7})
    with pytest.raises(ValueError, match="revision"):
        AssignmentRevocation("old", 7, {"primary": revision})


def test_revocation_pins_are_bounded_immutable_and_canonical():
    replacements = {"primary": 7, "backup": 8}
    pinned = AssignmentRevocation("old", 7, replacements)
    replacements["primary"] = 99
    assert pinned.replacement_revisions["primary"] == 7
    with pytest.raises(TypeError):
        pinned.replacement_revisions["primary"] = 99
    assert AssignmentRevocation.from_dict(pinned.to_dict()) == pinned
    for bad in ({}, {"old": 7}, {f"replacement-{index}": 7 for index in range(31)}):
        with pytest.raises(ValueError):
            AssignmentRevocation("old", 7, bad)
    with pytest.raises(ValueError, match="fields"):
        AssignmentRevocation.from_dict({**pinned.to_dict(), "approved": True})


async def test_grant_history_cannot_supply_the_new_revocation_review():
    cases = await _cases()
    draft = await cases.create_case(principal=_owner(), intent=_intent(), now=NOW)
    with pytest.raises(ValueError, match="independent review"):
        await cases.begin_iam_apply(
            case_id=draft.case_id, expected_revision=draft.revision, actor_ref="Thor"
        )
    assert (await cases.get_case("old")).state is AssignmentState.ACTIVE
    assert draft.reviews == ()


@pytest.mark.parametrize("change", ["subject", "role", "duty", "scope", "revision", "goals"])
async def test_revocation_cannot_substitute_another_target_or_duty(change):
    cases = await _cases()
    intent = _intent()
    if change == "subject":
        intent = replace(intent, subject=ProviderSubject("entra", "another-person"))
    elif change == "role":
        intent = replace(intent, requested_role=Role.CONTRIBUTOR)
    elif change in {"duty", "scope"}:
        intent = replace(
            intent,
            duty_bindings=(
                DutyBinding(
                    "Thor",
                    Duty.BACKUP if change == "duty" else Duty.PRIMARY,
                    "scope:other" if change == "scope" else "scope:platform",
                ),
            ),
        )
    elif change == "revision":
        intent = replace(intent, revocation=AssignmentRevocation("old", 6, {"primary": 7}))
    else:
        with pytest.raises(ValueError, match="goals"):
            replace(intent, goal_refs=("new-goal",))
        return
    with pytest.raises(ValueError, match="original grant"):
        await cases.create_case(principal=_owner(), intent=intent, now=NOW)


async def test_changed_replacement_pins_conflict_with_existing_idempotency_key():
    cases = await _cases()
    first = await cases.create_case(principal=_owner(), intent=_intent(), now=NOW)
    replay = await cases.create_case(principal=_owner(), intent=_intent(), now=NOW)
    assert replay == first
    altered = replace(_intent(), revocation=AssignmentRevocation("old", 7, {"primary": 8}))
    with pytest.raises(ValueError, match="different intent"):
        await cases.create_case(principal=_owner(), intent=altered, now=NOW)


async def test_old_duty_cannot_be_removed_before_iam_removal_effect():
    cases = await _cases()
    approved = await _reviewed(cases)
    with pytest.raises(ValueError, match="verified IAM removal"):
        await cases.open_ownership_pr(
            case_id=approved.case_id, expected_revision=approved.revision, actor_ref="delivery"
        )
    applying = await cases.begin_iam_apply(
        case_id=approved.case_id, expected_revision=approved.revision, actor_ref="Thor"
    )
    assert (await cases.get_case("old")).state is AssignmentState.DEGRADED
    assert applying.effect_receipts == ()
    with pytest.raises(ValueError):
        await cases.record_effect(
            case_id=applying.case_id,
            expected_revision=applying.revision,
            receipt=_effect(EffectKind.OWNERSHIP),
            actor_ref="delivery",
        )


async def test_only_two_ordered_effects_close_the_old_assignment():
    cases = await _cases()
    removed = await _removed(cases)
    assert removed.state is AssignmentState.IAM_REVOKED
    assert (await cases.get_case("old")).state is AssignmentState.DEGRADED
    opened = await cases.open_ownership_pr(
        case_id=removed.case_id, expected_revision=removed.revision, actor_ref="delivery"
    )
    closed = await cases.record_effect(
        case_id=opened.case_id,
        expected_revision=opened.revision,
        receipt=_effect(EffectKind.OWNERSHIP),
        actor_ref="signed-merge-observer",
    )
    assert closed.state is AssignmentState.REVOKED
    old = await cases.get_case("old")
    assert old.state is AssignmentState.SUPERSEDED
    assert old.superseded_by == old.revocation_case_id == closed.case_id
    assert old.effect_receipts == _old().effect_receipts
    assert old.intent == _old().intent
    before = tuple(cases.store.audit_entries)
    assert (
        await cases.record_effect(
            case_id=closed.case_id,
            expected_revision=opened.revision,
            receipt=_effect(EffectKind.OWNERSHIP),
            actor_ref="signed-merge-observer",
        )
        == closed
    )
    assert tuple(cases.store.audit_entries) == before


async def test_two_removal_cases_cannot_borrow_the_same_pre_effect_hold():
    cases = await _cases()
    first, second = await _reviewed(cases, "first"), await _reviewed(cases, "second")
    results = await asyncio.gather(
        *(
            cases.begin_iam_apply(
                case_id=case.case_id, expected_revision=case.revision, actor_ref="Thor"
            )
            for case in (first, second)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AssignmentCase) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    held = await cases.get_case("old")
    assert held.revocation_case_id in {first.case_id, second.case_id}


async def test_interrupted_case_transition_retains_and_reuses_its_own_hold():
    class FailingStore(InMemoryStateStore):
        fail_key = None

        async def compare_and_set_state_with_audit(self, key, value, **kwargs):
            if key == self.fail_key:
                self.fail_key = None
                raise RuntimeError("synthetic case write failure")
            return await super().compare_and_set_state_with_audit(key, value, **kwargs)

    store = FailingStore()
    cases = await _cases(store)
    approved = await _reviewed(cases)
    store.fail_key = f"human_assignment:case:{approved.case_id}"
    with pytest.raises(RuntimeError, match="synthetic"):
        await cases.begin_iam_apply(
            case_id=approved.case_id, expected_revision=approved.revision, actor_ref="Thor"
        )
    held = await cases.get_case("old")
    assert held.state is AssignmentState.DEGRADED
    restarted = AssignmentCaseService(store)
    applying = await restarted.begin_iam_apply(
        case_id=approved.case_id, expected_revision=approved.revision, actor_ref="Thor"
    )
    assert applying.state is AssignmentState.IAM_APPLYING
    assert await cases.get_case("old") == held


def test_removal_never_activates_and_old_hold_never_reactivates():
    with pytest.raises(ValueError, match="cannot activate"):
        replace(_old(), intent=_intent())
    with pytest.raises(ValueError, match="cannot become active"):
        replace(_old(), revocation_case_id="removal")


def test_grants_cannot_use_the_reverse_order_shortcut():
    approved = replace(_old(), state=AssignmentState.APPROVED, effect_receipts=())
    applying = replace(approved, revision=approved.revision + 1, state=AssignmentState.IAM_APPLYING)
    with pytest.raises(AssignmentTransitionError, match="grant cannot"):
        validate_transition(
            approved, applying, TransitionIntent(approved.revision, AssignmentState.IAM_APPLYING)
        )


def test_legacy_grants_keep_the_exact_serialized_intent_digest_inputs():
    stored = _old().to_dict()
    assert "revocation" not in stored["intent"]
    assert "revocation_case_id" not in stored
    assert AssignmentCase.from_dict(stored).to_dict() == stored


async def test_core_goal_mutation_stops_at_the_pre_effect_revocation_hold():
    cases = await _cases()
    goals = HandoverGoalService(store=cases.store, assignments=cases)
    goal = await goals.create_goal(
        assignment_case_id="old",
        agent_name="Thor",
        scope_ref="scope:platform",
        prompt_ref="goal-template:runbook-gaps:v1",
        priority=90,
        now=NOW,
    )
    approved = await _reviewed(cases)
    await cases.begin_iam_apply(
        case_id=approved.case_id, expected_revision=approved.revision, actor_ref="Thor", now=NOW
    )
    with pytest.raises(ValueError, match="active assignment"):
        await goals.add_evidence(
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            evidence=GoalEvidence("doc:example:v1", "a" * 64, "document_span"),
            now=NOW,
        )
