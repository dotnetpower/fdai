"""WorkflowApprovalPlanner tests.

Covers the workflow-layer approver-assignment bridge: per step, whether it is
an approval gate (derived from the ActionType ceiling), which Entra-backed role
approves it, and which notification channels reach the approver.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.notifications.matrix import (
    NotificationMatrix,
    load_matrix_from_mapping,
    load_matrix_from_yaml,
)
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.rbac.roles import Role
from fdai.core.workflow.approval import (
    ApprovalPlanError,
    WorkflowApprovalPlanner,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import (
    Autonomy,
    CeilingByTier,
    CeilingRole,
    Mode,
    OntologyActionType,
    Operation,
    ProdDowngrade,
    PromotionGate,
    RollbackKind,
    TierCeiling,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
PROBES_ROOT = REPO_ROOT / "rule-catalog" / "probes"
WORKFLOWS_ROOT = REPO_ROOT / "rule-catalog" / "workflows"
MATRIX_FILE = REPO_ROOT / "config" / "notifications-matrix.yaml"


def _group_mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="grp-readers",
        contributor_group_id="grp-contributors",
        approver_group_id="grp-approvers",
        owner_group_id="grp-owners",
        break_glass_group_id="grp-break-glass",
    )


def _matrix() -> NotificationMatrix:
    return load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "hil_approval",
                "routes": {
                    "hil_approval": {
                        "trust_tier": "a1_hil_approval",
                        "primary": "teams-hil-prd",
                        "fallback": ["slack-hil-prd", "email-approvers"],
                    }
                },
            }
        }
    )


def _action(
    name: str,
    *,
    ceiling: CeilingByTier | None = None,
    prod_downgrade: ProdDowngrade | None = None,
) -> OntologyActionType:
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
        ceiling_by_tier=ceiling,
        prod_downgrade=prod_downgrade,
    )


def _workflow(action_ref: str) -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="sample-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="object.drift"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[WorkflowStep(id="only", action_type_ref=action_ref)],
    )


def _planner(action: OntologyActionType) -> WorkflowApprovalPlanner:
    return WorkflowApprovalPlanner(
        action_types={action.name: action},
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )


def test_enforce_hil_tier_is_an_approval_gate() -> None:
    action = _action(
        "ops.restart",
        ceiling=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
            t1=TierCeiling(max_autonomy=Autonomy.SHADOW_ONLY, min_role=CeilingRole.APPROVER),
        ),
    )
    plan = _planner(action).plan(_workflow("ops.restart"))
    step = plan.steps[0]
    assert step.requires_approval is True
    assert step.required_role is Role.APPROVER
    assert step.entra_group_ref == "grp-approvers"
    assert step.notify_channels == ("teams-hil-prd", "slack-hil-prd", "email-approvers")
    assert step.self_approval_excluded is True
    assert plan.gated_steps == (step,)


def test_all_auto_is_not_an_approval_gate() -> None:
    action = _action(
        "remediate.auto",
        ceiling=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.CONTRIBUTOR),
        ),
    )
    plan = _planner(action).plan(_workflow("remediate.auto"))
    step = plan.steps[0]
    assert step.requires_approval is False
    assert step.required_role is None
    assert step.entra_group_ref is None
    assert step.notify_channels == ()
    assert plan.gated_steps == ()


def test_prod_downgrade_hil_drives_the_gate() -> None:
    action = _action(
        "ops.failover",
        ceiling=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.CONTRIBUTOR),
            t2=TierCeiling(max_autonomy=Autonomy.SHADOW_ONLY, min_role=CeilingRole.OWNER),
        ),
        prod_downgrade=ProdDowngrade(
            mode=Autonomy.ENFORCE_HIL, detection_ref="risk-classification/env-detector"
        ),
    )
    plan = _planner(action).plan(_workflow("ops.failover"))
    step = plan.steps[0]
    assert step.requires_approval is True
    # Only the prod downgrade drives HIL, so the role is the highest declared
    # tier min_role (owner).
    assert step.required_role is Role.OWNER
    assert step.entra_group_ref == "grp-owners"
    assert "prod_downgrade" in step.reason


def test_highest_hil_tier_role_wins() -> None:
    action = _action(
        "ops.big",
        ceiling=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
            t2=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.OWNER),
        ),
    )
    plan = _planner(action).plan(_workflow("ops.big"))
    assert plan.steps[0].required_role is Role.OWNER


def test_no_ceiling_defers_to_runtime() -> None:
    action = _action("remediate.plain")  # no ceiling, no prod downgrade
    plan = _planner(action).plan(_workflow("remediate.plain"))
    step = plan.steps[0]
    assert step.requires_approval is False
    assert "runtime risk-gate decides" in step.reason


def test_missing_action_type_raises() -> None:
    planner = WorkflowApprovalPlanner(
        action_types={},
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    with pytest.raises(ApprovalPlanError, match="not present in the planner's catalog"):
        planner.plan(_workflow("remediate.absent"))


def test_audit_dict_shape() -> None:
    action = _action(
        "ops.restart",
        ceiling=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
        ),
    )
    plan = _planner(action).plan(_workflow("ops.restart"))
    d = plan.to_audit_dict()
    assert d["workflow"] == "sample-flow"
    assert d["gated_step_count"] == 1
    assert d["steps"][0]["required_role"] == "Approver"
    assert d["steps"][0]["entra_group_ref"] == "grp-approvers"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def test_plan_shipped_workflows_against_real_catalog() -> None:
    registry = _registry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT,
        schema_registry=registry,
        probes_root=PROBES_ROOT if PROBES_ROOT.is_dir() else None,
    )
    workflows = load_workflow_catalog(
        WORKFLOWS_ROOT,
        schema_registry=registry,
        action_type_names={a.name for a in action_types},
    )
    planner = WorkflowApprovalPlanner(
        action_types={a.name: a for a in action_types},
        group_mapping=_group_mapping(),
        matrix=load_matrix_from_yaml(MATRIX_FILE),
    )
    for wf in workflows:
        plan = planner.plan(wf)
        assert len(plan.steps) == len(wf.steps)
        for step in plan.gated_steps:
            # A gated step always names an approver group and a channel.
            assert step.entra_group_ref is not None
            assert step.notify_channels, f"{wf.name}.{step.step_id}: gated but no channel"
            assert step.required_role in {Role.APPROVER, Role.OWNER, Role.CONTRIBUTOR}

    # dr-failover-drill uses ops.failover-primary (t0 enforce_hil) - it MUST
    # produce at least one gated step.
    dr = next(
        p for p in (planner.plan(w) for w in workflows) if p.workflow_name == "dr-failover-drill"
    )
    assert dr.gated_steps, "dr-failover-drill should have an approval-gated step"
