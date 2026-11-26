"""Materialize a schedule-triggered Workflow as a persistent scheduler task."""

from __future__ import annotations

import hashlib

from fdai.core.scheduler.models import ScheduledTask
from fdai.shared.contracts.models import Workflow, WorkflowTriggerKind


def scheduled_task_from_workflow(
    workflow: Workflow,
    *,
    target_resource_ref: str,
    artifact_ref: str,
    created_by: str,
    cron_expression: str | None = None,
) -> ScheduledTask:
    """Bind a catalog schedule to one target and one immutable task artifact."""

    if workflow.trigger.kind is not WorkflowTriggerKind.SCHEDULE:
        raise ValueError("workflow MUST use trigger.kind=schedule")
    if workflow.trigger.schedule is None:  # pragma: no cover - model invariant
        raise ValueError("scheduled workflow has no cron expression")
    if not target_resource_ref:
        raise ValueError("target_resource_ref MUST be non-empty")
    if not artifact_ref:
        raise ValueError("artifact_ref MUST be non-empty")
    action_steps = [step for step in workflow.steps if step.action_type_ref is not None]
    if len(action_steps) != 1:
        raise ValueError("scheduled action proposal workflow MUST contain exactly one action step")
    action_type = action_steps[0].action_type_ref
    if action_type is None:  # pragma: no cover - filtered invariant
        raise ValueError("scheduled action step has no ActionType")
    binding = hashlib.sha256(
        f"{workflow.name}\n{target_resource_ref}\n{artifact_ref}".encode()
    ).hexdigest()[:20]
    return ScheduledTask(
        task_id=f"workflow-{workflow.name}-{binding}",
        name=f"Workflow: {workflow.name}",
        interval_seconds=60,
        cron_expression=cron_expression or workflow.trigger.schedule,
        event_type=f"workflow.schedule.{workflow.name}",
        created_by=created_by,
        resource_ref=target_resource_ref,
        event_payload={
            "workflow_ref": workflow.name,
            "workflow_version": str(workflow.version),
            "task": {"artifact_ref": artifact_ref},
            "action_proposal": {
                "initiator_principal": created_by,
                "action_type": action_type,
                "params": {
                    "artifact_ref": artifact_ref,
                    "target_resource_ref": target_resource_ref,
                    "reason": f"Scheduled Workflow {workflow.name} invocation.",
                },
            },
        },
    )


__all__ = ["scheduled_task_from_workflow"]
