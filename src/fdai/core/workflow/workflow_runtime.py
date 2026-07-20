"""Workflow process identity, state records, and control helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome, RunbookStepResult
from fdai.core.workflow.approval import ApprovalPlan
from fdai.shared.providers.browser_evidence import BrowserEvidenceReceipt
from fdai.shared.providers.process_runtime import ProcessStatus

ACTOR = "fdai.core.workflow.orchestrator"
_PARAM_TOKEN = re.compile(r"\$\{([a-z0-9_.]+)\}")
_PROCESS_KEY_PREFIX = "process:"


def resolve_params(params: Mapping[str, object], context: Mapping[str, str]) -> dict[str, object]:
    """Substitute context tokens in string parameter values."""
    resolved: dict[str, object] = {}
    for key, value in params.items():
        if isinstance(value, str):
            resolved[key] = _PARAM_TOKEN.sub(
                lambda match: context.get(match.group(1), match.group(0)), value
            )
        else:
            resolved[key] = value
    return resolved


@runtime_checkable
class WorkflowGuardEvaluator(Protocol):
    """Evaluate a deterministic workflow step guard at run time."""

    async def evaluate(self, *, rule_id: str, step_id: str, process_id: str) -> bool:
        """Return whether the guard permits the step."""
        ...


@runtime_checkable
class WorkflowActionDispatcher(Protocol):
    """Republish one enforce action step into the typed control-loop ingress."""

    async def dispatch(
        self,
        *,
        process_id: str,
        correlation_id: str,
        step: RunbookStep,
        target_resource_id: str,
        params: Mapping[str, object],
        context: Mapping[str, str],
    ) -> str:
        """Return the durable proposal or idempotency reference."""
        ...


@runtime_checkable
class WorkflowEvidenceDispatcher(Protocol):
    """Submit one credential-free browser evidence request."""

    async def dispatch(
        self,
        *,
        process_id: str,
        correlation_id: str,
        step: RunbookStep,
        params: Mapping[str, object],
    ) -> BrowserEvidenceReceipt: ...


def process_state_key(process_id: str) -> str:
    """Return the state-store key for a process record."""
    return f"{_PROCESS_KEY_PREFIX}{process_id}"


def process_record(
    *,
    process_id: str,
    workflow_name: str,
    status: ProcessStatus,
    current_step: str,
    target_resource_id: str,
    started_at: datetime,
) -> dict[str, object]:
    """Build a Process ObjectType row."""
    return {
        "id": process_id,
        "workflow_ref": workflow_name,
        "status": status.value,
        "current_step": current_step,
        "target_resource_id": target_resource_id,
        "started_at": started_at.isoformat(),
    }


@dataclass(frozen=True, slots=True)
class ProcessRun:
    """The result of one shadow workflow run."""

    process_id: str
    workflow_name: str
    status: ProcessStatus
    step_results: tuple[RunbookStepResult, ...]
    approval_plan: ApprovalPlan
    replayed: bool = False
    mode: str = "shadow"


def derive_process_id(*, workflow_name: str, target_resource_id: str, trigger_ts: datetime) -> str:
    """Derive an idempotent process id from the workflow trigger tuple."""
    key = f"{workflow_name}:{target_resource_id}:{trigger_ts.isoformat()}"
    return str(uuid5(NAMESPACE_URL, key))


def event_id(process_id: str, suffix: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{process_id}:{suffix}"))


def step_result(
    step: RunbookStep,
    outcome: RunbookStepOutcome,
    reason: str,
) -> RunbookStepResult:
    return RunbookStepResult(
        step_id=step.id,
        action_type=step.action_type,
        outcome=outcome,
        reason=reason,
    )


def truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "received"}


def approval_decisions(context: Mapping[str, str], step_id: str) -> dict[str, str]:
    prefix = f"approval.{step_id}."
    decisions = {
        key.removeprefix(prefix): value.strip().lower()
        for key, value in context.items()
        if key.startswith(prefix) and key != f"{prefix}started_at"
    }
    legacy = context.get(f"approval.{step_id}")
    if legacy is not None:
        decisions.setdefault("legacy", legacy.strip().lower())
    return decisions
