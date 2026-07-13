"""Workflow approval planning - resolve, per step, whether it is an approval
gate and, if so, which Entra-backed role approves it and how the approver is
notified (see docs/roadmap/decisioning/process-automation.md 6).

This is the shadow-time / design-time answer to "who approves each step of a
workflow, and through which channel". It is **read-only and deterministic**: it
composes the existing machinery rather than adding a new one -

- the ActionType ``ceiling_by_tier`` / ``prod_downgrade`` is the single source
  of truth for whether a step routes to HIL (matches the risk decision in
  execution-model.md);
- the RBAC :class:`GroupMapping` maps a human role to its Entra security-group
  objectId;
- the notification :class:`NotificationMatrix` resolves the ``hil_approval``
  (A1) route to the ordered Teams / Slack / email channels.

The planner produces an :class:`ApprovalPlan` an orchestrator can audit before
it ever parks an action with the :class:`HilResumeCoordinator`. It never
executes, never notifies - it plans. Runtime approver assignment (the specific
on-call OID, the parked action, the Adaptive Card push) stays with the existing
:class:`~fdai.core.hil_resume.coordinator.HilResumeCoordinator` and
:class:`~fdai.core.oncall.resolver.OnCallResolver`; this planner is the
workflow-layer bridge that has been missing between a Workflow and that
machinery.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.notifications.matrix import NotificationMatrix
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.rbac.roles import Role
from fdai.shared.contracts.models import (
    Autonomy,
    CeilingRole,
    OntologyActionType,
    TierCeiling,
    Workflow,
    WorkflowStep,
    WorkflowStepKind,
)

_HIL_CATEGORY = "hil_approval"

_CEILING_TO_ROLE: Mapping[CeilingRole, Role] = {
    CeilingRole.READER: Role.READER,
    CeilingRole.CONTRIBUTOR: Role.CONTRIBUTOR,
    CeilingRole.APPROVER: Role.APPROVER,
    CeilingRole.OWNER: Role.OWNER,
}

_CEILING_RANK: Mapping[CeilingRole, int] = {
    CeilingRole.READER: 0,
    CeilingRole.CONTRIBUTOR: 1,
    CeilingRole.APPROVER: 2,
    CeilingRole.OWNER: 3,
}


class ApprovalPlanError(ValueError):
    """Raised when a workflow step references an ActionType the planner was
    not given. The workflow loader guarantees every ``action_type_ref``
    resolves, so this only fires when the planner is handed an inconsistent
    catalog subset - a programmer error, surfaced fail-closed."""


@dataclass(frozen=True, slots=True)
class StepApproval:
    """The approval assignment for one workflow step.

    ``requires_approval`` is derived from the step's ActionType ceiling; when
    True, ``required_role`` / ``entra_group_ref`` / ``notify_channels`` name the
    approver and how they are reached. ``self_approval_excluded`` is always True
    - it carries the no-self-approval invariant forward to the orchestrator.
    """

    step_id: str
    action_type: str
    requires_approval: bool
    reason: str
    required_role: Role | None
    entra_group_ref: str | None
    notify_channels: tuple[str, ...]
    self_approval_excluded: bool = True


@dataclass(frozen=True, slots=True)
class ApprovalPlan:
    """The per-step approval plan for one Workflow."""

    workflow_name: str
    steps: tuple[StepApproval, ...]

    @property
    def gated_steps(self) -> tuple[StepApproval, ...]:
        """The subset of steps that require a human approver."""
        return tuple(s for s in self.steps if s.requires_approval)

    def to_audit_dict(self) -> dict[str, object]:
        """A flat, secret-free view for the audit log / operator console."""
        return {
            "workflow": self.workflow_name,
            "gated_step_count": len(self.gated_steps),
            "steps": [
                {
                    "step_id": s.step_id,
                    "action_type": s.action_type,
                    "requires_approval": s.requires_approval,
                    "reason": s.reason,
                    "required_role": s.required_role.value if s.required_role else None,
                    "entra_group_ref": s.entra_group_ref,
                    "notify_channels": list(s.notify_channels),
                    "self_approval_excluded": s.self_approval_excluded,
                }
                for s in self.steps
            ],
        }


class WorkflowApprovalPlanner:
    """Resolve a :class:`ApprovalPlan` for a Workflow from the ActionType
    ceilings, the Entra group mapping, and the notification matrix."""

    __slots__ = ("_action_types", "_role_to_group", "_hil_channels")

    def __init__(
        self,
        *,
        action_types: Mapping[str, OntologyActionType],
        group_mapping: GroupMapping,
        matrix: NotificationMatrix,
    ) -> None:
        self._action_types = action_types
        self._role_to_group: Mapping[Role, str] = {
            Role.READER: group_mapping.reader_group_id,
            Role.CONTRIBUTOR: group_mapping.contributor_group_id,
            Role.APPROVER: group_mapping.approver_group_id,
            Role.OWNER: group_mapping.owner_group_id,
        }
        # The A1 approval route is fixed at construction so a plan is a pure
        # function of the workflow; the matrix cannot be swapped mid-plan.
        self._hil_channels: tuple[str, ...] = matrix.resolve(_HIL_CATEGORY).channel_ids

    def plan(self, workflow: Workflow) -> ApprovalPlan:
        """Return the per-step :class:`ApprovalPlan` for ``workflow``."""
        steps = tuple(self._plan_workflow_step(step) for step in workflow.steps)
        return ApprovalPlan(workflow_name=workflow.name, steps=steps)

    def _plan_workflow_step(self, step: WorkflowStep) -> StepApproval:
        if step.kind is WorkflowStepKind.ACTION:
            if step.action_type_ref is None:  # pragma: no cover - model invariant
                raise ApprovalPlanError(f"action step {step.id!r} has no ActionType")
            return self._plan_step(step_id=step.id, action_ref=step.action_type_ref)
        if step.kind is WorkflowStepKind.APPROVAL:
            if step.approval_role is None:  # pragma: no cover - model invariant
                raise ApprovalPlanError(f"approval step {step.id!r} has no role")
            role = _CEILING_TO_ROLE[step.approval_role]
            return StepApproval(
                step_id=step.id,
                action_type="workflow.approval",
                requires_approval=True,
                reason=f"explicit approval step; quorum={step.quorum}",
                required_role=role,
                entra_group_ref=self._role_to_group[role],
                notify_channels=self._hil_channels,
                self_approval_excluded=step.no_self_approval,
            )
        return StepApproval(
            step_id=step.id,
            action_type=f"workflow.{step.kind.value}",
            requires_approval=False,
            reason="control step has no direct ActionType approval ceiling",
            required_role=None,
            entra_group_ref=None,
            notify_channels=(),
        )

    def _plan_step(self, *, step_id: str, action_ref: str) -> StepApproval:
        action = self._action_types.get(action_ref)
        if action is None:
            raise ApprovalPlanError(
                f"workflow step {step_id!r} references ActionType {action_ref!r} "
                "not present in the planner's catalog"
            )

        requires, reason, role = _approval_for(action)
        if not requires:
            return StepApproval(
                step_id=step_id,
                action_type=action_ref,
                requires_approval=False,
                reason=reason,
                required_role=None,
                entra_group_ref=None,
                notify_channels=(),
            )
        return StepApproval(
            step_id=step_id,
            action_type=action_ref,
            requires_approval=True,
            reason=reason,
            required_role=role,
            entra_group_ref=self._role_to_group.get(role) if role else None,
            notify_channels=self._hil_channels,
        )


def _tiers(action: OntologyActionType) -> list[tuple[str, TierCeiling]]:
    ceiling = action.ceiling_by_tier
    if ceiling is None:
        return []
    return [
        (name, tier)
        for name, tier in (("t0", ceiling.t0), ("t1", ceiling.t1), ("t2", ceiling.t2))
        if tier is not None
    ]


def _highest_role(tiers: list[tuple[str, TierCeiling]]) -> CeilingRole | None:
    roles = [tier.min_role for _, tier in tiers]
    if not roles:
        return None
    return max(roles, key=lambda r: _CEILING_RANK[r])


def _approval_for(action: OntologyActionType) -> tuple[bool, str, Role | None]:
    """Decide whether an ActionType is an approval gate and, if so, the role.

    An ActionType routes to HIL when any tier ceiling is ``enforce_hil`` or its
    ``prod_downgrade`` collapses to ``enforce_hil``. The required approver role
    is the highest ``min_role`` across the HIL tiers (or, when only the prod
    downgrade drives HIL, across all declared tiers).
    """
    tiers = _tiers(action)
    hil_tiers = [(name, tier) for name, tier in tiers if tier.max_autonomy is Autonomy.ENFORCE_HIL]

    if hil_tiers:
        highest_hil = _highest_role(hil_tiers)
        role = _CEILING_TO_ROLE[highest_hil] if highest_hil is not None else Role.APPROVER
        names = ", ".join(name for name, _ in hil_tiers)
        return True, f"ceiling max_autonomy=enforce_hil at tier(s) {names}", role

    downgrade = action.prod_downgrade
    if downgrade is not None and downgrade.mode is Autonomy.ENFORCE_HIL:
        highest = _highest_role(tiers)
        role = _CEILING_TO_ROLE[highest] if highest is not None else Role.APPROVER
        return True, "prod_downgrade mode=enforce_hil", role

    return False, "no enforce_hil ceiling or prod HIL downgrade; runtime risk-gate decides", None


__all__ = [
    "ApprovalPlan",
    "ApprovalPlanError",
    "StepApproval",
    "WorkflowApprovalPlanner",
]
