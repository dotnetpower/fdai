"""Read-only current-case membership planning with no provider or workload identity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fdai.core.human_assignment.coverage import approval_quorum_satisfied
from fdai.core.human_assignment.model import AssignmentState, EffectKind
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.roles import Role
from fdai.shared.providers.human_access import HumanAccessOperation, HumanAccessPlan


@dataclass(frozen=True, slots=True)
class HumanAccessPlanner:
    """Read a reviewed assignment and pin its group; a plan is never execution approval."""

    cases: AssignmentCaseService
    role_group_ids: Mapping[Role, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_group_ids", MappingProxyType(dict(self.role_group_ids)))

    async def plan(self, *, case_id: str, expected_revision: int) -> HumanAccessPlan:
        """Refuse stale, unreviewed, removal-held or non-Entra grants without any state write."""
        case = await self.cases.get_case(case_id)
        if case.intent.revocation is not None or case.revocation_case_id:
            raise ValueError("grant planning cannot reactivate a revocation-held assignment")
        if type(expected_revision) is not int or case.revision != expected_revision:
            raise ValueError("human access plan requires the exact current case revision")
        if case.intent.subject.provider != "entra":
            raise ValueError("human access plan subject provider is unsupported")
        if not approval_quorum_satisfied(case.intent, case.reviews):
            raise ValueError("human access plan requires independent case approval")
        if case.state not in {
            AssignmentState.OWNERSHIP_MERGED,
            AssignmentState.IAM_APPLYING,
            AssignmentState.DEGRADED,
        }:
            raise ValueError("human access apply requires a merged ownership effect")
        if EffectKind.OWNERSHIP not in case.effect_kinds:
            raise ValueError("human access apply requires an ownership effect receipt")
        group = self.role_group_ids.get(case.intent.requested_role)
        if group is None or case.intent.requested_role is Role.BREAK_GLASS:
            raise ValueError("requested role has no routine allowlisted group")
        return HumanAccessPlan(
            case_id=case.case_id,
            subject_id=case.intent.subject.subject_id,
            group_id=group,
            operation=HumanAccessOperation.GRANT,
            idempotency_key=f"human-access:{case.case_id}",
        )


__all__ = ["HumanAccessPlanner"]
