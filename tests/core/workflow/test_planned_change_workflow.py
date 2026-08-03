from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.workflow import (
    ChangeWindowWorkflowGuardEvaluator,
    WorkflowApprovalPlanner,
    WorkflowOrchestrator,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.process_runtime import ProcessStatus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 8, 4, tzinfo=UTC)


class _ChangeWindows:
    def __init__(self, *, active: bool) -> None:
        self.active = active

    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        del target_ref, at
        return self.active


@pytest.mark.parametrize(
    ("window_active", "expected_status"),
    [(False, ProcessStatus.FAILED), (True, ProcessStatus.WAITING)],
)
async def test_planned_change_window_precedes_quorum_approval(
    window_active: bool,
    expected_status: ProcessStatus,
) -> None:
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
    with (_ROOT / "config" / "rbac-groups.yaml").open(encoding="utf-8") as handle:
        group_mapping = GroupMapping.from_config(yaml.safe_load(handle))
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=actions,
            group_mapping=group_mapping,
            matrix=load_matrix_from_yaml(_ROOT / "config" / "notifications-matrix.yaml"),
        ),
        action_types=actions,
        audit_store=InMemoryStateStore(),
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=ChangeWindowWorkflowGuardEvaluator(
            change_windows=_ChangeWindows(active=window_active)
        ),
    )

    run = await orchestrator.run(
        workflow,
        target_resource_id="resource-1",
        trigger_ts=_NOW,
        context={"requester.principal": "operator-1"},
    )

    assert run.status is expected_status
    assert run.step_results[0].reason == ("gate_passed" if window_active else "gate_blocked")
    if window_active:
        assert run.step_results[1].reason == "waiting_for_approval"
