from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.workflow.definition import (
    build_workflow_definition,
    built_in_workflow_lifecycle,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.workflow_definition import (
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _catalogs() -> tuple:
    registry = PackageResourceSchemaRegistry()
    actions = load_action_type_catalog(
        ROOT / "rule-catalog" / "action-types",
        schema_registry=registry,
    )
    workflows = load_workflow_catalog(
        ROOT / "rule-catalog" / "workflows",
        schema_registry=registry,
        action_type_names={item.name for item in actions},
    )
    return workflows, {item.name: item for item in actions}


def test_definition_pins_workflow_and_action_catalog_deterministically() -> None:
    workflows, actions = _catalogs()
    workflow = workflows[0]
    first = build_workflow_definition(
        workflow,
        action_types=actions,
        origin=WorkflowOrigin.UPSTREAM,
        visibility=WorkflowVisibility.GLOBAL,
        lifecycle=WorkflowLifecycle.SHADOW,
        created_at=NOW,
        source_ref="git:catalog",
    )
    second = build_workflow_definition(
        workflow,
        action_types=actions,
        origin=WorkflowOrigin.UPSTREAM,
        visibility=WorkflowVisibility.GLOBAL,
        lifecycle=WorkflowLifecycle.SHADOW,
        created_at=NOW,
        source_ref="git:catalog",
    )

    assert first == second
    assert first.definition_hash.startswith("sha256:")
    assert first.action_catalog_digest.startswith("sha256:")
    assert set(first.resolved_action_versions) == {
        step.action_type_ref for step in workflow.steps if step.action_type_ref is not None
    }
    assert first.workflow_document["name"] == workflow.name


def test_definition_rejects_missing_action_type() -> None:
    workflows, actions = _catalogs()
    workflow = next(item for item in workflows if any(step.action_type_ref for step in item.steps))
    referenced = next(step.action_type_ref for step in workflow.steps if step.action_type_ref)
    actions.pop(referenced)

    with pytest.raises(ValueError, match="unknown ActionTypes"):
        build_workflow_definition(
            workflow,
            action_types=actions,
            origin=WorkflowOrigin.UPSTREAM,
            visibility=WorkflowVisibility.GLOBAL,
            lifecycle=WorkflowLifecycle.SHADOW,
            created_at=NOW,
        )


def test_built_in_lifecycle_uses_shared_promotion_state() -> None:
    promoted = frozenset({"cost-aware-remediation"})

    assert (
        built_in_workflow_lifecycle(
            "cost-aware-remediation",
            promoted_workflows=promoted,
        )
        is WorkflowLifecycle.PUBLISHED
    )
    assert (
        built_in_workflow_lifecycle(
            "architecture-review",
            promoted_workflows=promoted,
        )
        is WorkflowLifecycle.SHADOW
    )
