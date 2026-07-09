"""Process automation - compile a declarative Workflow into an executable
Runbook (see docs/roadmap/process-automation.md).

The runtime instance and state of a running Workflow is the ``Process``
ontology ObjectType; this package holds the compile step that turns a
catalog Workflow into the thin :class:`~fdai.core.runbook.models.Runbook`
the existing :class:`~fdai.core.runbook.runner.RunbookRunner` executes.
"""

from __future__ import annotations

from .approval import (
    ApprovalPlan,
    ApprovalPlanError,
    StepApproval,
    WorkflowApprovalPlanner,
)
from .compiler import CompiledWorkflow, compile_workflow
from .coordinator import WorkflowTriggerCoordinator
from .orchestrator import (
    ProcessRun,
    ProcessStatus,
    ShadowWorkflowStepExecutor,
    WorkflowOrchestrator,
    derive_process_id,
)
from .trigger_index import WorkflowTriggerIndex

__all__ = [
    "ApprovalPlan",
    "ApprovalPlanError",
    "CompiledWorkflow",
    "ProcessRun",
    "ProcessStatus",
    "ShadowWorkflowStepExecutor",
    "StepApproval",
    "WorkflowApprovalPlanner",
    "WorkflowOrchestrator",
    "WorkflowTriggerCoordinator",
    "WorkflowTriggerIndex",
    "compile_workflow",
    "derive_process_id",
]
