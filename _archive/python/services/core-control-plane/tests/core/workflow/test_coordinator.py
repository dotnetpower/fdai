"""WorkflowTriggerCoordinator tests - Event -> matched Workflows -> shadow run."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.coordinator import WorkflowTriggerCoordinator
from fdai.core.workflow.orchestrator import WorkflowOrchestrator, derive_process_id
from fdai.core.workflow.schedule import scheduled_task_from_workflow
from fdai.core.workflow.trigger_index import WorkflowTriggerIndex
from fdai.shared.contracts.models import (
    Autonomy,
    CeilingByTier,
    CeilingRole,
    Event,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    TierCeiling,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_TS = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _action(name: str) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.RESTART,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        description="Test action.",
        ceiling_by_tier=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
        ),
    )


_ACTION_TYPES = {"ops.gated": _action("ops.gated")}


def _wf(name: str, signal: str) -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type=signal),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[WorkflowStep(id="s", action_type_ref="ops.gated")],
    )


def _scheduled_wf() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="scheduled-gpu-task",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SCHEDULE, schedule="0 2 * * *"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=30,
            min_accuracy=0.99,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="run",
                action_type_ref="ops.gated",
                params={
                    "artifact_ref": "${event.payload.task.artifact_ref}",
                    "target": "${event.resource_ref}",
                },
            )
        ],
    )


def _group_mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="grp-readers",
        contributor_group_id="grp-contributors",
        approver_group_id="grp-approvers",
        owner_group_id="grp-owners",
        break_glass_group_id="grp-break-glass",
    )


def _matrix():  # type: ignore[no-untyped-def]
    return load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "hil_approval",
                "routes": {
                    "hil_approval": {
                        "trust_tier": "a1_hil_approval",
                        "primary": "teams-hil-prd",
                        "fallback": ["slack-hil-prd"],
                    }
                },
            }
        }
    )


def _coordinator(
    audit: InMemoryStateStore, workflows: list[Workflow]
) -> WorkflowTriggerCoordinator:
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
    )
    index = WorkflowTriggerIndex.build(workflows)
    return WorkflowTriggerCoordinator(index=index, orchestrator=orchestrator)


def _event(
    *, event_type: str, resource_ref: str | None = "res-1", payload: dict | None = None
) -> Event:
    return Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key="idem-1",
        source="test",
        event_type=event_type,
        resource_ref=resource_ref,
        payload=payload or {},
        detected_at=_TS,
        ingested_at=_TS,
        mode=Mode.SHADOW,
    )


async def test_matched_event_runs_workflow_in_shadow() -> None:
    audit = InMemoryStateStore()
    coord = _coordinator(audit, [_wf("on-drift", "object.drift")])
    runs = await coord.on_event(_event(event_type="object.drift"))
    assert [r.workflow_name for r in runs] == ["on-drift"]
    # The run produced the expected audit trail.
    kinds = [row["entry"]["action_kind"] for row in audit.audit_entries]
    assert "workflow.process-plan" in kinds
    assert "workflow.step" in kinds


async def test_unmatched_event_starts_nothing() -> None:
    audit = InMemoryStateStore()
    coord = _coordinator(audit, [_wf("on-drift", "object.drift")])
    runs = await coord.on_event(_event(event_type="cost.anomaly"))
    assert runs == ()
    assert list(audit.audit_entries) == []


async def test_multiple_matched_run_in_name_order() -> None:
    audit = InMemoryStateStore()
    coord = _coordinator(
        audit,
        [_wf("zeta", "object.drift"), _wf("alpha", "object.drift")],
    )
    runs = await coord.on_event(_event(event_type="object.drift"))
    assert [r.workflow_name for r in runs] == ["alpha", "zeta"]


async def test_process_id_uses_event_resource_and_timestamp() -> None:
    audit = InMemoryStateStore()
    coord = _coordinator(audit, [_wf("on-drift", "object.drift")])
    (run,) = await coord.on_event(_event(event_type="object.drift", resource_ref="res-9"))
    assert run.process_id == derive_process_id(
        workflow_name="on-drift", target_resource_id="res-9", trigger_ts=_TS
    )


async def test_payload_resource_fallback() -> None:
    audit = InMemoryStateStore()
    coord = _coordinator(audit, [_wf("on-drift", "object.drift")])
    event = _event(
        event_type="object.drift",
        resource_ref=None,
        payload={"resource": {"resource_id": "res-from-payload"}},
    )
    (run,) = await coord.on_event(event)
    assert run.process_id == derive_process_id(
        workflow_name="on-drift", target_resource_id="res-from-payload", trigger_ts=_TS
    )


async def test_resourceless_event_uses_sentinel_target() -> None:
    audit = InMemoryStateStore()
    coord = _coordinator(audit, [_wf("on-drift", "object.drift")])
    (run,) = await coord.on_event(_event(event_type="object.drift", resource_ref=None))
    assert run.process_id == derive_process_id(
        workflow_name="on-drift",
        target_resource_id="event:object.drift",
        trigger_ts=_TS,
    )


async def test_scheduled_event_runs_bound_workflow_and_templates_payload() -> None:
    audit = InMemoryStateStore()
    workflow = _scheduled_wf()
    task = scheduled_task_from_workflow(
        workflow,
        target_resource_ref="resource:compute/vm/gpu-worker",
        artifact_ref="python-task:gpu.health@1.0.0#" + "a" * 64,
        created_by="operator-1",
    )
    event = _event(
        event_type=task.event_type,
        resource_ref=task.resource_ref,
        payload=dict(task.event_payload),
    )
    proposal = task.event_payload["action_proposal"]
    assert set(proposal["params"]) == {"artifact_ref", "target_resource_ref", "reason"}

    runs = await _coordinator(audit, [workflow]).on_event(event)

    assert [run.workflow_name for run in runs] == [workflow.name]
    step = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"] == "workflow.step"
    )
    assert step["params"]["artifact_ref"].startswith("python-task:gpu.health@")
    assert step["params"]["target"] == "resource:compute/vm/gpu-worker"
