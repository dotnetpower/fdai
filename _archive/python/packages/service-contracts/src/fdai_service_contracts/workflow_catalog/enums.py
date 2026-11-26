"""Workflow catalog enum vocabulary shared by Core and Operator."""

from __future__ import annotations

from enum import StrEnum


class Mode(StrEnum):
    """Autonomy mode at the time of processing."""

    SHADOW = "shadow"
    ENFORCE = "enforce"


class CeilingRole(StrEnum):
    """Ordinary RBAC ladder used by workflow approval and action ceilings."""

    READER = "reader"
    CONTRIBUTOR = "contributor"
    APPROVER = "approver"
    OWNER = "owner"


CEILING_ROLE_RANK: dict[CeilingRole, int] = {
    CeilingRole.READER: 0,
    CeilingRole.CONTRIBUTOR: 1,
    CeilingRole.APPROVER: 2,
    CeilingRole.OWNER: 3,
}


class WorkflowTriggerKind(StrEnum):
    """How a Workflow run is started."""

    SIGNAL = "signal"
    SCHEDULE = "schedule"


class WorkflowTriggerSignalReferenceKind(StrEnum):
    """Catalog that resolved a signal-trigger reference."""

    SIGNAL_TYPE = "signal_type"
    WORKFLOW_TRIGGER_EVENT = "workflow_trigger_event"


class WorkflowStepKind(StrEnum):
    """Typed behavior of one Workflow step."""

    ACTION = "action"
    WAIT = "wait"
    APPROVAL = "approval"
    DECISION = "decision"
    PARALLEL = "parallel"
    GATE = "gate"
    EVIDENCE = "evidence"


__all__ = [
    "CEILING_ROLE_RANK",
    "CeilingRole",
    "Mode",
    "WorkflowStepKind",
    "WorkflowTriggerKind",
    "WorkflowTriggerSignalReferenceKind",
]
