"""Only the development Owner's attested, revalidated self-approval dispatches a category park.

Ordinary approvers are refused while anyone authorized may reject, and the admitted
self-approval dispatches only after the ControlLoop reruns its full current evaluation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.hil_resume import ResolveOutcome
from fdai.core.hil_resume.development import DEVELOPMENT_ADMISSION_ACTOR, CategoryRevalidation
from fdai.core.risk_gate.risk_table import load_risk_table_from_mapping
from fdai.delivery import development_bindings
from fdai.shared.contracts.development_authority import canonical_authority_digest
from fdai.shared.contracts.models import Action, Rule
from fdai.shared.providers.execution_authorization import ExecutionAuthorizationStatus
from fdai.shared.providers.hil_channel import HilDecision

from tests.core.hil_resume.development_category_harness import (
    DRIFTED,
    OTHER_APPROVER,
    CategoryScenario,
)
from tests.core.hil_resume.test_development_self_approval import REVISION


async def test_the_revalidator_refuses_a_park_it_cannot_verify() -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()
    action = Action.model_validate(parked["action"])
    rule = Rule.model_validate(parked["rule"])
    loop = scenario.loop

    async def reason(candidate: Mapping[str, Any]) -> str:
        result = await loop.revalidate_category_park(candidate, action=action, rule=rule)
        assert result.eligible is (result.reason_code == "category_revalidated")
        return result.reason_code

    def reblocked(*, drop: tuple[str, ...] = (), **changes: Any) -> dict[str, Any]:
        body = {
            key: value
            for key, value in parked["development_authority"].items()
            if key != "block_digest" and key not in drop
        }
        body.update(changes)
        block = {**body, "block_digest": canonical_authority_digest(body)}
        return {**parked, "development_authority": block}

    event = parked["development_authority"]["evaluation_event"]
    assert await reason(parked) == "category_revalidated"
    tampered = {
        **parked,
        "development_authority": {**parked["development_authority"], "category_denial": {}},
    }
    assert await reason(tampered) == "park_block_invalid"
    ordinary = reblocked(drop=("owner_self_approval_only",), original_level="hil")
    assert await reason(ordinary) == "park_block_invalid"
    assert await reason(reblocked(evaluation_event={"event_id": "x"})) == (
        "evaluation_event_invalid"
    )
    other_event = {**event, "event_id": "00000000-0000-0000-0000-0000000000ff"}
    assert await reason(reblocked(evaluation_event=other_event)) == "evaluation_event_invalid"
    assert await reason(reblocked(category_denial=None)) == "category_denial_changed"
    loop._development_revision_reader = None
    assert await reason(parked) == "category_revalidation_unwired"
    loop._development_revision_reader = scenario.revisions
    loop._execution_authorization_evaluator = None
    assert await reason(parked) == "execution_authorization_changed"
    loop._execution_authorization_evaluator = scenario.authorization
    loop._risk_gate = None
    assert await reason(parked) == "risk_evaluation_unavailable"


async def test_ordinary_approvers_are_refused_and_any_approver_may_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()
    approval_id = str(parked["approval_id"])
    scenario.record_dispatch(monkeypatch)

    refused = await scenario.coordinator.resolve(
        approval_id=approval_id,
        decision=HilDecision.APPROVE,
        approver_oid=OTHER_APPROVER,
    )

    assert refused.outcome is ResolveOutcome.OWNER_SELF_APPROVAL_REQUIRED
    assert scenario.dispatched == []
    still_pending = await scenario.store.read_state(f"hil_park:{approval_id}")
    assert still_pending is not None and still_pending["status"] == "pending"
    assert scenario.audits("hil.resolve.development_owner_only_refused")[-1]["approver_oid"] == (
        OTHER_APPROVER
    )
    # The Owner's own attestation does not let another approver stand in for the Owner.
    borrowed = await scenario.attest(parked, signed=scenario.base + timedelta(seconds=60))
    scenario.clock[0] = scenario.base + timedelta(minutes=2)
    impersonated = await scenario.coordinator.resolve(
        approval_id=approval_id,
        decision=HilDecision.APPROVE,
        approver_oid=OTHER_APPROVER,
        development_attestation=borrowed,
    )
    assert impersonated.outcome is ResolveOutcome.OWNER_SELF_APPROVAL_REQUIRED
    uncapable = await scenario.coordinator.resolve(
        approval_id=approval_id,
        decision=HilDecision.APPROVE,
        approver_oid=OTHER_APPROVER,
        approver_can_approve_hil=False,
    )
    assert uncapable.outcome is ResolveOutcome.MISSING_CAPABILITY
    unattested = await scenario.coordinator.resolve(
        approval_id=approval_id,
        decision=HilDecision.APPROVE,
        approver_oid=scenario.owner,
    )
    assert unattested.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert scenario.dispatched == []
    still_pending = await scenario.store.read_state(f"hil_park:{approval_id}")
    assert still_pending is not None and still_pending["status"] == "pending"

    rejected = await scenario.coordinator.resolve(
        approval_id=approval_id,
        decision=HilDecision.REJECT,
        approver_oid=OTHER_APPROVER,
        reason="Not in this test window.",
    )

    assert rejected.outcome is ResolveOutcome.REJECTED
    assert scenario.dispatched == []


async def test_the_requesting_owner_may_reject_the_category_park(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()
    approval_id = str(parked["approval_id"])
    scenario.record_dispatch(monkeypatch)

    rejected = await scenario.coordinator.resolve(
        approval_id=approval_id,
        decision=HilDecision.REJECT,
        approver_oid=scenario.owner,
        reason="Withdrawn by the requesting Owner.",
    )

    assert rejected.outcome is ResolveOutcome.REJECTED
    assert scenario.dispatched == []
    closed = await scenario.store.read_state(f"hil_park:{approval_id}")
    assert closed is not None
    assert (closed["status"], closed["decision"], closed["approver_oid"]) == (
        "resolved",
        "reject",
        scenario.owner,
    )


async def test_admission_refuses_a_binding_narrower_than_the_blast_radius(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario(resource_group_bound=True)
    with monkeypatch.context() as forged:
        # Record the target's resource-group scope, as a forged or pre-widening binding would.
        forged.setattr(
            development_bindings,
            "action_scope",
            lambda profile, action, action_type: development_bindings.target_scope(
                profile, action.target_resource_ref
            ),
        )
        await scenario.request()
    parked = await scenario.parked()

    result = await scenario.owner_approves(monkeypatch)

    assert result.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert result.reason == "binding_scope_mismatch"
    assert scenario.dispatched == []
    closed = await scenario.store.read_state(f"hil_park:{parked['approval_id']}")
    assert closed is not None
    assert (closed["status"], closed["approver_oid"]) == ("resolved", DEVELOPMENT_ADMISSION_ACTOR)


async def test_owner_self_approval_dispatches_only_after_full_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()

    result = await scenario.owner_approves(monkeypatch)

    assert result.outcome is ResolveOutcome.EXECUTION_PENDING
    assert [str(action.action_id) for action in scenario.dispatched] == [
        parked["action"]["action_id"]
    ]
    # The subscription-wide blast radius needs, and the profile binds, the whole subscription.
    verification = await scenario.registry.read_verification(parked["action"]["action_id"])
    assert verification is not None
    assert verification.binding.scope.resource_group_digests == ()
    assert scenario.profile.scope.covers(verification.binding.scope)
    admitted = scenario.audits("hil.resolve.development_self_approval")[-1]
    assert admitted["original_level"] == "deny"
    assert admitted["effective_quorum"] == 1
    assert admitted["category_revalidation"]["eligible"] is True
    assert admitted["category_revalidation"]["execution_authorization"] == "authorized"
    # Park and revalidation each ran the full authorization and risk evaluation.
    assert len(scenario.authorization.requests) == 2
    assert [entry["decision"] for entry in scenario.audits("risk_gate.unified")] == [
        "deny",
        "deny",
    ]


async def test_owner_self_approval_needs_a_fresh_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()
    stale = await scenario.attest(parked, signed=scenario.base - timedelta(seconds=5))
    scenario.clock[0] = scenario.base + timedelta(minutes=2)
    scenario.record_dispatch(monkeypatch)

    result = await scenario.coordinator.resolve(
        approval_id=str(parked["approval_id"]),
        decision=HilDecision.APPROVE,
        approver_oid=scenario.owner,
        development_attestation=stale,
    )

    assert result.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert result.reason == "authentication_not_fresh"
    assert scenario.dispatched == []


def _without_category_rule() -> Any:
    return load_risk_table_from_mapping(
        {
            "version": "9.0.0",
            "owner_group": "aw-owners",
            "rules": [{"id": "default-hil", "default": "hil", "reason": "fail closed"}],
        }
    )


def _with_a_stricter_residual() -> Any:
    return load_risk_table_from_mapping(
        {
            "version": "9.0.0",
            "owner_group": "aw-owners",
            "rules": [
                {
                    "id": "deny-subscription-blast",
                    "if": {"blast_radius": "subscription"},
                    "decision": "deny",
                    "reason": "category",
                },
                {
                    "id": "hil-reversible-quorum",
                    "if": {"reversible": True},
                    "decision": "hil",
                    "quorum": 2,
                    "reason": "residual requirement changed after the park",
                },
                {"id": "default-hil", "default": "hil", "reason": "fail closed"},
            ],
        }
    )


@pytest.mark.parametrize(
    ("gate", "reason"),
    [
        ("kill_switch", "category_denial_changed"),
        ("degraded", "category_denial_changed"),
        ("evidence_conflict_unreadable", "category_denial_changed"),
        ("evidence_conflict_active", "category_denial_changed"),
        ("automation_hold", "category_denial_changed"),
        ("risk_table_changed", "category_denial_changed"),
        ("risk_table_residual_changed", "category_denial_changed"),
        ("inventory_unreadable", "current_inventory_unavailable"),
        ("authorization_prohibited", "execution_authorization_changed"),
        ("executor_identity_changed", "execution_authorization_changed"),
        ("demoted_to_shadow", "promotion_mode_changed"),
        ("revision_drift_after_admission", "target_revision_drift"),
        ("revision_drift_before_admission", "target_revision_drift"),
        # The Core-prepared binding never outlives the profile, so expiry fails the binding first.
        ("profile_expired", "binding_mismatch"),
        ("revalidator_unwired", "category_revalidation_unwired"),
        ("revalidator_failed", "category_revalidation_failed"),
    ],
)
async def test_each_current_gate_blocks_dispatch(
    gate: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = CategoryScenario(
        profile_shift=timedelta(minutes=-59) if gate == "profile_expired" else timedelta(0)
    )
    await scenario.request()
    parked = await scenario.parked()
    if gate == "kill_switch":
        scenario.kill_switch.engage()
    scenario.degradation.permitted = gate != "degraded"
    scenario.conflicts.unreadable = gate == "evidence_conflict_unreadable"
    scenario.conflicts.active = gate == "evidence_conflict_active"
    scenario.hold.held = gate == "automation_hold"
    scenario.inventory.unreadable = gate == "inventory_unreadable"
    if gate == "risk_table_changed":
        scenario.loop._risk_table = _without_category_rule()
    if gate == "risk_table_residual_changed":
        scenario.loop._risk_table = _with_a_stricter_residual()
    if gate == "authorization_prohibited":
        scenario.authorization.status = ExecutionAuthorizationStatus.PROHIBITED
    if gate == "executor_identity_changed":
        scenario.authorization.identity = "identity/other"
    if gate == "demoted_to_shadow":
        scenario.promotion.demote(scenario.action_type.name)
    if gate == "revision_drift_after_admission":
        scenario.revisions.queued = [REVISION, DRIFTED]
    if gate == "revision_drift_before_admission":
        scenario.revisions.default = DRIFTED
    if gate == "revalidator_unwired":
        scenario.coordinator._development_category_revalidator = None
    if gate == "revalidator_failed":

        class _Failing:
            async def revalidate_category_park(self, *_: Any, **__: Any) -> CategoryRevalidation:
                raise RuntimeError("current evaluation failed")

        scenario.coordinator._development_category_revalidator = _Failing()

    result = await scenario.owner_approves(monkeypatch)

    assert result.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert result.reason == reason
    assert scenario.dispatched == []
    closed = await scenario.store.read_state(f"hil_park:{parked['approval_id']}")
    assert closed is not None
    assert (closed["status"], closed["decision"], closed["approver_oid"]) == (
        "resolved",
        "reject",
        DEVELOPMENT_ADMISSION_ACTOR,
    )
    refused = scenario.audits("hil.resolve.development_self_approval_refused")[-1]
    assert refused["reason_code"] == reason
