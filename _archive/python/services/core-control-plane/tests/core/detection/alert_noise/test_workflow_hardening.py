"""Round 10: exact reviewed Workflow composition and identity are never replaceable defaults."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.detection.alert_noise.execution import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.workflow import AlertWorkflowCoordinator
from fdai.core.detection.alert_noise.workflow_catalog import (
    alert_workflow_for_plan,
    alert_workflow_target,
    workflow_binding_key,
)
from fdai.shared.contracts.models import CeilingRole
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertRollbackBaseline

from .test_workflow import _approve, _promote_actions, _retain_promotion
from .test_workflow import workflow_harness as workflow_harness


@pytest.mark.parametrize("missing", ["workflow", "action", "restore", "action_alias"])
async def test_catalog_dependencies_are_exact(workflow_harness, missing: str) -> None:
    h = workflow_harness
    workflows, actions = dict(h.workflows), dict(h.actions)
    if missing == "workflow":
        workflows.clear()
    elif missing == "action_alias":
        actions[h.plan.action_type] = actions[RESTORE_ACTION]
    else:
        actions.pop(h.plan.action_type if missing == "action" else RESTORE_ACTION)
    with pytest.raises(AlertExecutionHeld):
        alert_workflow_for_plan(h.plan, workflows=workflows, action_types=actions)
    assert not tuple(h.store.audit_entries)


@pytest.mark.parametrize(
    "change",
    [
        {"quorum": 1},
        {"approval_role": CeilingRole.APPROVER},
        {"params": {"plan_digest": "other"}},
        {"id": "other_approval"},
    ],
)
async def test_reviewed_approval_step_cannot_be_replaced(workflow_harness, change: dict) -> None:
    h = workflow_harness
    original = h.workflows["alert-routing-change"]
    changed = original.model_copy(
        update={"steps": [original.steps[0].model_copy(update=change), original.steps[1]]}
    )
    with pytest.raises(ValueError):
        alert_workflow_for_plan(h.plan, workflows={original.name: changed}, action_types=h.actions)
    assert not tuple(h.store.audit_entries)


async def test_rollback_and_target_identity_are_both_bound(workflow_harness) -> None:
    h = workflow_harness
    baseline = AlertRollbackBaseline(rule=h.evidence.rules[0])
    assert alert_workflow_target(h.plan, baseline) == h.plan.treatment.target_ref
    wrong = baseline.model_copy(
        update={"rule": baseline.rule.model_copy(update={"revision": "sha256:" + "f" * 64})}
    )
    for plan in (
        h.plan,
        h.plan.model_copy(update={"rollback_ref": digest_record(wrong)}),
    ):
        with pytest.raises(AlertExecutionHeld):
            alert_workflow_target(plan, wrong)
    with pytest.raises(AlertExecutionHeld, match="identity"):
        workflow_binding_key("invalid/process")


@pytest.mark.parametrize("correlation", ["", " padded", "padded "])
async def test_invalid_correlation_creates_no_process(workflow_harness, correlation: str) -> None:
    h = workflow_harness
    with pytest.raises(AlertExecutionHeld, match="correlation"):
        await h.coordinator.create(**{**h.inputs, "correlation_id": correlation})
    assert not tuple(h.store.audit_entries)


async def test_requester_replacement_during_create_is_held(workflow_harness) -> None:
    h = workflow_harness
    subject = h.subjects[h.plan.requester_ref]
    resolver = SimpleNamespace(resolve=AsyncMock(side_effect=[subject, "other-principal"]))
    coordinator = AlertWorkflowCoordinator(**{**h.options, "requesters": resolver})
    with pytest.raises(AlertExecutionHeld, match="requester_changed"):
        await coordinator.create(**h.inputs)
    assert not tuple(h.store.audit_entries)


async def test_terminal_failed_replay_does_not_reinvoke(workflow_harness) -> None:
    h = workflow_harness
    _promote_actions(h)
    await _retain_promotion(h)
    first = await h.coordinator.run(**h.inputs)
    await _approve(h, first.process_id, admit=False)
    failed = await h.coordinator.resume(process_id=first.process_id)
    assert failed.status.terminal
    count = len(tuple(h.store.audit_entries))
    replay = await h.coordinator.resume(process_id=first.process_id)
    assert replay == failed and len(tuple(h.store.audit_entries)) == count
