"""A category-only denial of the development Owner's own request parks for that Owner alone.

Outside a current profile, its scope, the Owner's own request, or a category-only denial, the
ordinary denial stands.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fdai.core.control_loop import ControlLoopOutcome
from fdai.core.risk_gate.category_denial import CategoryDenial
from fdai.delivery.development_bindings import BINDING_PREFIX
from fdai.shared.contracts.models import Action, Event, Mode, Rule, WorkflowActionRef
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai_service_contracts.development_approval import development_owner_only

from tests.core.hil_resume.development_category_harness import CategoryScenario
from tests.core.hil_resume.test_development_self_approval import (
    IDENTITY_REF,
    SUBSCRIPTION,
    TARGET,
)
from tests.core.hil_resume.test_development_self_approval import _Scenario as _OwnerParkScenario

OTHER_SUBSCRIPTION = "00000000-0000-0000-0000-00000000de02"


async def test_owner_category_denial_parks_owner_only_inside_the_profile() -> None:
    scenario = CategoryScenario()

    result = await scenario.request()

    assert result.outcome is ControlLoopOutcome.HIL
    parked = await scenario.parked()
    block = parked["development_authority"]
    assert development_owner_only(parked)
    assert (block["original_level"], block["effective_quorum"]) == ("deny", 1)
    assert block["owner_self_approval_only"] is True
    assert block["category_denial"]["rule_ids"] == ["deny-subscription-blast"]
    assert block["category_denial"]["axes"] == ["risk_table", "static_blast"]
    assert block["evaluation_event"]["resource_ref"] == TARGET
    assert parked["submitter_oid"] == scenario.owner
    assert parked["action"]["mode"] == Mode.ENFORCE.value
    assert parked["action"]["executor_identity_ref"] == IDENTITY_REF
    assert scenario.audits("risk_gate.unified")[-1]["decision"] == "deny"
    park_audit = scenario.audits("risk_gate.development_category_park")[-1]
    assert (park_audit["original_decision"], park_audit["decision"]) == ("deny", "hil")
    assert park_audit["block_digest"] == block["block_digest"]
    assert await scenario.bindings() == 1


async def test_category_block_needs_a_current_profile_and_records_the_residual_quorum() -> None:
    category = CategoryDenial(
        rule_ids=("deny-subscription-blast",),
        axes=("risk_table", "static_blast"),
        residual_rule_id="hil-irreversible",
        residual_decision="hil",
        residual_quorum=2,
    )
    unified = SimpleNamespace(decision="deny", quorum=1)

    def event(at: datetime) -> Event:
        return Event(
            schema_version="1.0.0",
            event_id=UUID("00000000-0000-0000-0000-000000000011"),
            idempotency_key="owner::category-1",
            source="operator",
            event_type="operator_request",
            resource_ref=TARGET,
            detected_at=at,
            ingested_at=at,
            mode=Mode.SHADOW,
        )

    current = _OwnerParkScenario()
    block = await current.block(
        unified=unified,
        category_denial=category,
        evaluation_event=event(current.base),
        now=current.base,
    )

    assert block is not None
    assert (block["original_level"], block["original_quorum"], block["effective_quorum"]) == (
        "deny",
        2,
        1,
    )
    assert block["owner_self_approval_only"] is True
    assert block["category_denial"] == category.as_audit_dict()
    assert block["evaluation_event"] == event(current.base).model_dump(mode="json")
    for overrides in (
        {"now": timedelta(hours=2)},
        {"now": timedelta(hours=-2)},
        {"now": None},
        {"evaluation_event": None},
    ):
        scenario = _OwnerParkScenario()
        shift = overrides.get("now", timedelta(0))
        arguments: dict[str, Any] = {
            "unified": unified,
            "category_denial": category,
            "evaluation_event": overrides.get("evaluation_event", event(scenario.base)),
            "now": None if shift is None else scenario.base + shift,
        }
        assert await scenario.block(**arguments) is None
        # A refused category park records no binding.
        assert (
            await scenario.store.read_state(BINDING_PREFIX + str(scenario.action.action_id)) is None
        )


@pytest.mark.parametrize(
    "case",
    [
        "non_owner",
        "outside_scope",
        "blast_radius_beyond_bound_groups",
        "profile_expired",
        "profile_not_yet_valid",
        "profile_absent",
        "kill_switch",
        "degraded",
        "evidence_conflict_unreadable",
        "evidence_conflict_active",
        "automation_hold",
        "authorization_prohibited",
    ],
)
async def test_every_other_denial_or_scope_still_denies(case: str) -> None:
    shifts = {
        "profile_expired": timedelta(hours=-3),
        "profile_not_yet_valid": timedelta(hours=3),
    }
    scenario = CategoryScenario(
        profile_shift=shifts.get(case, timedelta(0)),
        with_profile=case != "profile_absent",
        resource_group_bound=case == "blast_radius_beyond_bound_groups",
    )
    if case == "kill_switch":
        scenario.kill_switch.engage()
    scenario.degradation.permitted = case != "degraded"
    scenario.conflicts.unreadable = case == "evidence_conflict_unreadable"
    scenario.conflicts.active = case == "evidence_conflict_active"
    scenario.hold.held = case == "automation_hold"
    if case == "authorization_prohibited":
        scenario.authorization.status = ExecutionAuthorizationStatus.PROHIBITED

    result = await scenario.request(
        initiator="human:someone-else" if case == "non_owner" else None,
        target=TARGET.replace(SUBSCRIPTION, OTHER_SUBSCRIPTION)
        if case == "outside_scope"
        else TARGET,
    )

    assert result.outcome is ControlLoopOutcome.DENIED
    assert scenario.channel.sent == []
    assert scenario.audits("risk_gate.development_category_park") == []
    assert await scenario.bindings() == 0


async def test_a_workflow_step_keeps_the_category_denial() -> None:
    scenario = CategoryScenario()
    await scenario.request()
    parked = await scenario.parked()
    event = Event.model_validate(parked["development_authority"]["evaluation_event"])
    action = Action.model_validate(parked["action"])
    rule = Rule.model_validate(parked["rule"])
    unified = await scenario.loop._evaluate_and_audit(event=event, action=action, rule=rule)
    assert unified is not None and unified.is_denied
    arguments: dict[str, Any] = {
        "event": event,
        "rule": rule,
        "authorization": ExecutionAuthorizationResult(
            status=ExecutionAuthorizationStatus.AUTHORIZED,
            decision_digest="sha256:" + "a" * 64,
            evaluator_ref="test",
            reason_codes=("authorized",),
            executor_identity_ref=IDENTITY_REF,
        ),
        "unified": unified,
        "initiator": scenario.owner,
        "correlation_id": "category-correlation",
    }
    workflow_step = action.model_copy(
        update={
            "workflow_action": WorkflowActionRef(
                process_id="process-1",
                step_id="step-1",
                proposal_ref=event.idempotency_key,
            )
        }
    )

    assert await scenario.loop._park_development_category_denial(action=action, **arguments)
    assert not await scenario.loop._park_development_category_denial(
        action=workflow_step, **arguments
    )
