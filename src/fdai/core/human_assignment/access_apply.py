"""Shadow-first coordinator for an assignment case's IAM membership effect."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai.core.human_assignment.model import AssignmentState, EffectKind, EffectReceipt
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.roles import Role
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.human_access import (
    HumanAccessOperation,
    HumanAccessPlan,
    HumanAccessProvisioner,
    HumanAccessReceipt,
)


class HumanAccessExecutionOutcome(StrEnum):
    PLANNED = "planned"
    APPLIED = "applied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HumanAccessExecution:
    outcome: HumanAccessExecutionOutcome
    plan: HumanAccessPlan
    receipt: HumanAccessReceipt | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class HumanAccessApplyCoordinator:
    cases: AssignmentCaseService
    provisioner: HumanAccessProvisioner
    role_group_ids: Mapping[Role, str]

    async def execute(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_ref: str,
        mode: Mode = Mode.SHADOW,
    ) -> HumanAccessExecution:
        assignment_case = await self.cases.get_case(case_id)
        if assignment_case.state not in {
            AssignmentState.OWNERSHIP_MERGED,
            AssignmentState.IAM_APPLYING,
            AssignmentState.DEGRADED,
        }:
            raise ValueError("human access apply requires a merged ownership effect")
        if EffectKind.OWNERSHIP not in assignment_case.effect_kinds:
            raise ValueError("human access apply requires an ownership effect receipt")
        group_id = self.role_group_ids.get(assignment_case.intent.requested_role)
        if group_id is None or assignment_case.intent.requested_role is Role.BREAK_GLASS:
            raise ValueError("requested role has no routine allowlisted group")
        plan = HumanAccessPlan(
            case_id=assignment_case.case_id,
            subject_id=assignment_case.intent.subject.subject_id,
            group_id=group_id,
            operation=HumanAccessOperation.GRANT,
            idempotency_key=f"human-access:{assignment_case.case_id}",
        )
        if mode is Mode.SHADOW:
            return HumanAccessExecution(HumanAccessExecutionOutcome.PLANNED, plan)

        applying = await self.cases.begin_iam_apply(
            case_id=assignment_case.case_id,
            expected_revision=expected_revision,
            actor_ref=actor_ref,
        )
        try:
            receipt = await self.provisioner.apply(plan)
            if not await self.provisioner.verify(plan):
                try:
                    await self.provisioner.rollback(plan)
                    reason_code = "iam_postcondition_failed_rolled_back"
                except Exception:  # noqa: BLE001 - provider boundary fails closed
                    reason_code = "iam_postcondition_failed_rollback_failed"
                degraded = await self.cases.mark_degraded(
                    case_id=applying.case_id,
                    expected_revision=applying.revision,
                    reason_code=reason_code,
                    actor_ref=actor_ref,
                )
                return HumanAccessExecution(
                    HumanAccessExecutionOutcome.FAILED,
                    plan,
                    receipt,
                    degraded.degraded_reason,
                )
            await self.cases.record_effect(
                case_id=applying.case_id,
                expected_revision=applying.revision,
                receipt=EffectReceipt(
                    kind=EffectKind.IAM,
                    receipt_ref=receipt.receipt_ref,
                    digest=receipt.digest,
                    received_at=datetime.now(UTC),
                ),
                actor_ref=actor_ref,
            )
            return HumanAccessExecution(HumanAccessExecutionOutcome.APPLIED, plan, receipt)
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            current = await self.cases.get_case(applying.case_id)
            if current.state is AssignmentState.IAM_APPLYING:
                await self.cases.mark_degraded(
                    case_id=current.case_id,
                    expected_revision=current.revision,
                    reason_code="iam_provider_failed",
                    actor_ref=actor_ref,
                )
            return HumanAccessExecution(
                HumanAccessExecutionOutcome.FAILED,
                plan,
                reason=type(exc).__name__,
            )


__all__ = [
    "HumanAccessApplyCoordinator",
    "HumanAccessExecution",
    "HumanAccessExecutionOutcome",
]
