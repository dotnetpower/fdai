"""Replacement plans are read-only and cannot remove still-required access."""

from __future__ import annotations

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
    ProviderSubject,
)
from fdai.core.human_assignment.replacement import ReplacementCoveragePlanner
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _active(case_id, subject, duty=Duty.PRIMARY, agent="Thor", scope="scope:platform"):
    return AssignmentCase(
        case_id=case_id,
        intent=AssignmentIntent(
            idempotency_key=case_id,
            subject=ProviderSubject("entra", subject),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding(agent, duty, scope),),
            goal_refs=(),
            requester_ref="human:requester",
            justification="Synthetic replacement coverage.",
        ),
        state=AssignmentState.ACTIVE,
        revision=7,
        effect_receipts=tuple(
            EffectReceipt(kind, f"receipt:{kind.value}:{case_id}", "a" * 64, NOW)
            for kind in (EffectKind.OWNERSHIP, EffectKind.IAM)
        ),
    )


async def _planner(*extra):
    store = InMemoryStateStore()
    cases = (
        _active("old", "human:old"),
        _active("primary", "human:new"),
        _active("backup", "human:backup", Duty.BACKUP),
        *extra,
    )
    for case in cases:
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())
    return ReplacementCoveragePlanner(AssignmentCaseService(store), {Role.READER: "group:reader"})


async def _plan(planner):
    return await planner.plan(
        case_id="old", expected_revision=7, replacement_revisions={"primary": 7, "backup": 7}
    )


async def test_complete_replacement_produces_only_an_inert_ordered_plan():
    planner = await _planner()
    before = await planner.cases.get_case("old")
    plan = await _plan(planner)
    assert plan.removal.operation.value == "revoke"
    assert plan.covered_slots == (("Thor", "scope:platform"),)
    assert plan.remaining_steps[-1] == "reviewed_old_duty_removal"
    assert await planner.cases.get_case("old") == before
    assert not tuple(planner.cases.store.audit_entries)


@pytest.mark.parametrize(
    "revisions", [{}, {"old": 7}, {"primary": 7}, {"backup": 7}, {"primary": 6, "backup": 7}]
)
async def test_incomplete_or_stale_replacement_is_held(revisions):
    planner = await _planner()
    with pytest.raises(ValueError):
        await planner.plan(case_id="old", expected_revision=7, replacement_revisions=revisions)


@pytest.mark.parametrize(
    "alteration", ["same_person", "wrong_scope", "wrong_agent", "not_active", "missing_effect"]
)
async def test_replacement_cannot_borrow_unrelated_or_unconverged_coverage(alteration):
    primary = _active("primary", "human:new")
    if alteration == "same_person":
        primary = replace(
            primary, intent=replace(primary.intent, subject=ProviderSubject("entra", " HUMAN:OLD "))
        )
    elif alteration == "wrong_scope":
        primary = _active("primary", "human:new", scope="scope:other")
    elif alteration == "wrong_agent":
        primary = _active("primary", "human:new", agent="Odin")
    elif alteration == "not_active":
        primary = replace(
            primary, state=AssignmentState.DEGRADED, degraded_reason="provider_unknown"
        )
    else:
        primary = replace(
            primary,
            state=AssignmentState.OWNERSHIP_MERGED,
            effect_receipts=primary.effect_receipts[:1],
        )
    planner = await _planner(primary)
    with pytest.raises(ValueError):
        await _plan(planner)


async def test_another_active_assignment_preserves_existing_role_membership():
    planner = await _planner(_active("unrelated", "human:old", agent="Odin"))
    with pytest.raises(ValueError, match="still required"):
        await _plan(planner)


async def test_unrelated_other_role_does_not_expand_the_single_role_removal():
    other = _active("unrelated", "human:old", agent="Odin")
    other = replace(other, intent=replace(other.intent, requested_role=Role.CONTRIBUTOR))
    planner = await _planner(other)
    plan = await _plan(planner)
    assert plan.removal.group_id == "group:reader"
    assert (await planner.cases.get_case("unrelated")).state is AssignmentState.ACTIVE


@pytest.mark.parametrize("state", [AssignmentState.IAM_APPLYING, AssignmentState.DEGRADED])
async def test_uncertain_or_degraded_other_grant_preserves_existing_membership(state):
    other = replace(
        _active("other", "human:old", agent="Odin"),
        state=state,
        degraded_reason="verification_pending" if state is AssignmentState.DEGRADED else None,
    )
    planner = await _planner(other)
    with pytest.raises(ValueError, match="still required"):
        await _plan(planner)


async def test_shadow_plan_retry_identity_is_stable_and_unchanged_inputs_are_read_only():
    planner = await _planner()
    assert await _plan(planner) == await _plan(planner)
    assert not tuple(planner.cases.store.audit_entries)
