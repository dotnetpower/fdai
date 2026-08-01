from __future__ import annotations

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
    HumanAccessApplyCoordinator,
    HumanAccessExecutionOutcome,
    ProviderSubject,
    ReviewDecision,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.human_access import (
    HumanAccessOutcome,
    HumanAccessPlan,
    HumanAccessReceipt,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class RecordingProvisioner:
    def __init__(self, *, verifies: bool = True, rollback_fails: bool = False) -> None:
        self.verifies = verifies
        self.rollback_fails = rollback_fails
        self.applied: list[HumanAccessPlan] = []
        self.rolled_back: list[HumanAccessPlan] = []

    async def apply(self, plan: HumanAccessPlan) -> HumanAccessReceipt:
        self.applied.append(plan)
        return HumanAccessReceipt(HumanAccessOutcome.APPLIED, "entra:receipt-1", "a" * 64)

    async def verify(self, plan: HumanAccessPlan) -> bool:
        return self.verifies

    async def rollback(self, plan: HumanAccessPlan) -> HumanAccessReceipt:
        self.rolled_back.append(plan)
        if self.rollback_fails:
            raise RuntimeError("synthetic rollback failure")
        return HumanAccessReceipt(HumanAccessOutcome.ROLLED_BACK, "entra:rollback-1", "b" * 64)


def _owner(oid: str) -> Principal:
    return Principal(oid=oid, roles=frozenset({Role.OWNER}))


async def _ownership_merged(service: AssignmentCaseService) -> AssignmentCase:
    created = await service.create_case(
        principal=_owner("requester-1"),
        intent=AssignmentIntent(
            idempotency_key="access-apply-1",
            subject=ProviderSubject("entra", "target-1"),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Odin", Duty.BACKUP, "scope:platform"),),
            goal_refs=(),
            requester_ref="requester-1",
            justification="Assign Reader access after ownership convergence.",
        ),
        now=datetime(2026, 8, 1, tzinfo=UTC),
    )
    pending = await service.submit_for_review(
        principal=_owner("requester-1"),
        case_id=created.case_id,
        expected_revision=created.revision,
    )
    approved = await service.review(
        principal=_owner("reviewer-1"),
        case_id=pending.case_id,
        expected_revision=pending.revision,
        decision=ReviewDecision.APPROVE,
    )
    opened = await service.open_ownership_pr(
        case_id=approved.case_id,
        expected_revision=approved.revision,
        actor_ref="governance",
    )
    return await service.record_effect(
        case_id=opened.case_id,
        expected_revision=opened.revision,
        receipt=EffectReceipt(
            EffectKind.OWNERSHIP,
            "github:pr-1",
            "digest-ownership",
            datetime(2026, 8, 1, 0, 5, tzinfo=UTC),
        ),
        actor_ref="github:reviewer",
    )


async def test_shadow_plans_without_mutation_or_state_change() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    merged = await _ownership_merged(cases)
    provisioner = RecordingProvisioner()
    coordinator = HumanAccessApplyCoordinator(cases, provisioner, {Role.READER: "group-reader"})

    result = await coordinator.execute(
        case_id=merged.case_id,
        expected_revision=merged.revision,
        actor_ref="Thor",
    )

    assert result.outcome is HumanAccessExecutionOutcome.PLANNED
    assert provisioner.applied == []
    assert (await cases.get_case(merged.case_id)).state is AssignmentState.OWNERSHIP_MERGED


async def test_degraded_case_without_ownership_receipt_cannot_plan_access() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    created = await cases.create_case(
        principal=_owner("requester-1"),
        intent=AssignmentIntent(
            idempotency_key="access-apply-without-ownership",
            subject=ProviderSubject("entra", "target-1"),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Odin", Duty.BACKUP, "scope:platform"),),
            goal_refs=(),
            requester_ref="requester-1",
            justification="Prove degraded state does not replace ownership evidence.",
        ),
    )
    pending = await cases.submit_for_review(
        principal=_owner("requester-1"),
        case_id=created.case_id,
        expected_revision=created.revision,
    )
    approved = await cases.review(
        principal=_owner("reviewer-1"),
        case_id=pending.case_id,
        expected_revision=pending.revision,
        decision=ReviewDecision.APPROVE,
    )
    degraded = await cases.mark_degraded(
        case_id=approved.case_id,
        expected_revision=approved.revision,
        reason_code="ownership_provider_failed",
        actor_ref="governance",
    )
    provisioner = RecordingProvisioner()
    coordinator = HumanAccessApplyCoordinator(
        cases,
        provisioner,
        {Role.READER: "group-reader"},
    )

    with pytest.raises(ValueError, match="ownership effect receipt"):
        await coordinator.execute(
            case_id=degraded.case_id,
            expected_revision=degraded.revision,
            actor_ref="Thor",
        )

    assert provisioner.applied == []


async def test_enforce_applies_verifies_and_activates() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    merged = await _ownership_merged(cases)
    provisioner = RecordingProvisioner()
    coordinator = HumanAccessApplyCoordinator(cases, provisioner, {Role.READER: "group-reader"})

    result = await coordinator.execute(
        case_id=merged.case_id,
        expected_revision=merged.revision,
        actor_ref="Thor",
        mode=Mode.ENFORCE,
    )

    assert result.outcome is HumanAccessExecutionOutcome.APPLIED
    assert (await cases.get_case(merged.case_id)).state is AssignmentState.ACTIVE


async def test_failed_postcondition_rolls_back_and_degrades() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    merged = await _ownership_merged(cases)
    provisioner = RecordingProvisioner(verifies=False)
    coordinator = HumanAccessApplyCoordinator(cases, provisioner, {Role.READER: "group-reader"})

    result = await coordinator.execute(
        case_id=merged.case_id,
        expected_revision=merged.revision,
        actor_ref="Thor",
        mode=Mode.ENFORCE,
    )

    held = await cases.get_case(merged.case_id)
    assert result.outcome is HumanAccessExecutionOutcome.FAILED
    assert provisioner.rolled_back
    assert held.state is AssignmentState.DEGRADED
    assert held.degraded_reason == "iam_postcondition_failed_rolled_back"


async def test_failed_rollback_is_distinct_degraded_state() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    merged = await _ownership_merged(cases)
    provisioner = RecordingProvisioner(verifies=False, rollback_fails=True)
    coordinator = HumanAccessApplyCoordinator(cases, provisioner, {Role.READER: "group-reader"})

    result = await coordinator.execute(
        case_id=merged.case_id,
        expected_revision=merged.revision,
        actor_ref="Thor",
        mode=Mode.ENFORCE,
    )

    held = await cases.get_case(merged.case_id)
    assert result.outcome is HumanAccessExecutionOutcome.FAILED
    assert held.state is AssignmentState.DEGRADED
    assert held.degraded_reason == "iam_postcondition_failed_rollback_failed"
