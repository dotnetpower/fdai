"""Direct-API adapter for reviewed human assignment cases."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.human_assignment import (
    HumanAccessApplyCoordinator,
    HumanAccessExecutionOutcome,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)

APPLY_HUMAN_ACCESS_ACTION = "ops.apply-human-access"
REVOKE_HUMAN_ACCESS_ACTION = "ops.revoke-human-access"
HUMAN_ACCESS_ACTIONS = frozenset({APPLY_HUMAN_ACCESS_ACTION, REVOKE_HUMAN_ACCESS_ACTION})


@dataclass(frozen=True, slots=True)
class HumanAccessDirectApiExecutor:
    coordinator: HumanAccessApplyCoordinator

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name not in HUMAN_ACCESS_ACTIONS:
            raise DirectApiPreconditionError("human access adapter received an unsupported action")
        if request.mode is Mode.ENFORCE:
            raise DirectApiPromotionError(
                "human access enforce mode requires a separately reviewed promotion"
            )
        if request.action_type_name == REVOKE_HUMAN_ACCESS_ACTION:
            raise DirectApiPreconditionError(
                "human access revocation requires a reviewed replacement-coverage case"
            )
        if set(request.arguments) != {"case_id", "expected_revision"}:
            raise DirectApiPreconditionError(
                "human access arguments MUST contain only case_id and expected_revision"
            )
        case_id = request.arguments.get("case_id")
        expected_revision = request.arguments.get("expected_revision")
        if not isinstance(case_id, str) or not case_id:
            raise DirectApiPreconditionError("human access case_id is required")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            raise DirectApiPreconditionError(
                "human access expected_revision MUST be a positive integer"
            )
        if request.resource_ref != f"human-assignment:{case_id}":
            raise DirectApiPreconditionError(
                "human access resource_ref does not match the assignment case"
            )
        execution = await self.coordinator.execute(
            case_id=case_id,
            expected_revision=expected_revision,
            actor_ref="Thor",
            mode=request.mode,
        )
        if execution.outcome is HumanAccessExecutionOutcome.PLANNED:
            return DirectApiReceipt(
                DirectApiOutcome.SUCCEEDED,
                f"human-access-plan:{request.action_id}",
                detail="shadow human access plan verified; no Graph mutation submitted",
            )
        if execution.outcome is HumanAccessExecutionOutcome.APPLIED and execution.receipt:
            return DirectApiReceipt(
                DirectApiOutcome.SUCCEEDED,
                execution.receipt.receipt_ref,
                detail="human access membership converged",
            )
        return DirectApiReceipt(
            DirectApiOutcome.FAILED,
            f"human-access-failed:{request.action_id}",
            rollback_succeeded=(execution.reason == "iam_postcondition_failed_rolled_back"),
            detail="human access apply failed closed",
        )


__all__ = [
    "APPLY_HUMAN_ACCESS_ACTION",
    "HUMAN_ACCESS_ACTIONS",
    "HumanAccessDirectApiExecutor",
    "REVOKE_HUMAN_ACCESS_ACTION",
]
