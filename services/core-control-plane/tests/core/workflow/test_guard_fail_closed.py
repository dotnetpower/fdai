"""Fail-closed guard evaluation for the concrete workflow guard binding.

Covers workflow-control-loop-integration.md section 4.2: a bound guard evaluator
resolves each step's `gate_ref`, and missing, stale, malformed, or unavailable
evidence can only block the step - never let it proceed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.workflow import (
    ChangeWindowWorkflowGuardEvaluator,
    WorkflowApprovalPlanner,
    WorkflowOrchestrator,
)
from fdai.core.workflow.gate_resolver import ChangeWindowGateEvidence
from fdai.core.workflow.workflow_runtime import WorkflowContextualGuardEvaluator
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import Workflow
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.process_runtime import ProcessStatus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[5]


class _UnavailableWindows:
    """Authoritative evidence source that cannot answer right now."""

    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        del target_ref, at
        raise ConnectionError("change-window evidence is unavailable")


class _MalformedGuard:
    """Deployment evaluator that violates the boolean guard contract."""

    async def evaluate_context(
        self,
        *,
        rule_id: str,
        step_id: str,
        process_id: str,
        target_resource_id: str,
        at: datetime,
    ) -> bool:
        del rule_id, step_id, process_id, target_resource_id, at
        return cast(bool, "active")


class _ActiveWindows:
    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        del target_ref, at
        return True


class _NoWindows:
    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        del target_ref, at
        return False


def _workflow() -> tuple[Workflow, dict[str, Any]]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(
        _ROOT / "rule-catalog" / "action-types",
        schema_registry=registry,
        probes_root=_ROOT / "rule-catalog" / "probes",
    )
    actions = {item.name: item for item in action_types}
    workflows = load_workflow_catalog(
        _ROOT / "rule-catalog" / "workflows",
        schema_registry=registry,
        action_type_names=set(actions),
    )
    workflow = next(item for item in workflows if item.name == "planned-vm-start-change")
    return workflow, actions


def _orchestrator(
    *,
    guard_evaluator: object,
    actions: dict[str, Any],
    audit: InMemoryStateStore,
) -> WorkflowOrchestrator:
    with (_ROOT / "config" / "rbac-groups.yaml").open(encoding="utf-8") as handle:
        group_mapping = GroupMapping.from_config(yaml.safe_load(handle))
    return WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=actions,
            group_mapping=group_mapping,
            matrix=load_matrix_from_yaml(_ROOT / "config" / "notifications-matrix.yaml"),
        ),
        action_types=actions,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=cast(WorkflowContextualGuardEvaluator, guard_evaluator),
    )


def _guard_rows(audit: InMemoryStateStore) -> list[dict[str, Any]]:
    return [
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "workflow.step"
        and row["entry"].get("guard_evaluated") is True
    ]


async def _run(
    guard_evaluator: object,
    *,
    now: datetime | None = None,
) -> tuple[ProcessStatus, str | None, list[dict[str, Any]]]:
    workflow, actions = _workflow()
    audit = InMemoryStateStore()
    orchestrator = _orchestrator(guard_evaluator=guard_evaluator, actions=actions, audit=audit)

    run = await orchestrator.run(
        workflow,
        target_resource_id="resource-1",
        trigger_ts=datetime.now(tz=UTC),
        context={"requester.principal": "operator-1"},
        now=now,
    )
    return run.status, run.step_results[0].reason, _guard_rows(audit)


async def test_unavailable_guard_evidence_blocks_the_step() -> None:
    status, reason, rows = await _run(
        ChangeWindowWorkflowGuardEvaluator(
            change_windows=cast(ChangeWindowGateEvidence, _UnavailableWindows())
        )
    )

    assert status is ProcessStatus.FAILED
    assert reason == "gate_blocked"
    assert rows[0]["guard_passed"] is False
    assert rows[0]["guard_error"] == "guard_evaluator_error:ConnectionError"


async def test_malformed_guard_result_blocks_the_step() -> None:
    status, reason, rows = await _run(_MalformedGuard())

    assert status is ProcessStatus.FAILED
    assert reason == "gate_blocked"
    assert rows[0]["guard_passed"] is False
    assert rows[0]["guard_error"] == "guard_result_malformed"


async def test_missing_window_evidence_blocks_the_step_without_an_error() -> None:
    # The evidence source answered, but no effective window covers the target, so the
    # guard is a clean policy block rather than an evaluation failure.
    status, reason, rows = await _run(
        ChangeWindowWorkflowGuardEvaluator(
            change_windows=cast(ChangeWindowGateEvidence, _NoWindows()),
            fallback=None,
        ),
    )

    assert status is ProcessStatus.FAILED
    assert reason == "gate_blocked"
    assert rows[0]["guard_passed"] is False
    assert rows[0]["guard_error"] is None


async def test_active_window_evidence_passes_the_guard() -> None:
    status, reason, rows = await _run(
        ChangeWindowWorkflowGuardEvaluator(
            change_windows=cast(ChangeWindowGateEvidence, _ActiveWindows())
        ),
    )

    assert status is ProcessStatus.WAITING
    assert reason == "gate_passed"
    assert rows[0]["guard_passed"] is True
    assert rows[0]["guard_error"] is None


async def test_stale_evaluation_clock_blocks_the_step() -> None:
    status, reason, rows = await _run(
        ChangeWindowWorkflowGuardEvaluator(
            change_windows=cast(ChangeWindowGateEvidence, _ActiveWindows())
        ),
        now=datetime.now(tz=UTC) - timedelta(hours=2),
    )

    assert status is ProcessStatus.FAILED
    assert reason == "gate_blocked"
    assert rows[0]["guard_passed"] is False
    assert rows[0]["guard_error"] == "guard_evidence_stale"


def test_guard_evidence_age_must_be_positive() -> None:
    from fdai.core.workflow.workflow_step_executor import ShadowWorkflowStepExecutor

    with pytest.raises(ValueError, match="guard_evidence_max_age MUST be positive"):
        ShadowWorkflowStepExecutor(
            process_id="process-1",
            action_types={},
            audit_store=InMemoryStateStore(),
            approvals={},
            process_store=InMemoryProcessRuntimeStore(),
            snapshot=cast(Any, object()),
            guard_evidence_max_age=timedelta(0),
        )
