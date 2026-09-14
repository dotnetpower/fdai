"""Direct-API adapter for reviewed human assignment cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.human_assignment import (
    HumanAccessApplyCoordinator,
    HumanAccessExecutionOutcome,
)
from fdai.core.human_assignment.replacement import ReplacementCoveragePlanner
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
    replacement: ReplacementCoveragePlanner | None = None

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name not in HUMAN_ACCESS_ACTIONS:
            raise DirectApiPreconditionError("human access adapter received an unsupported action")
        if request.mode is Mode.ENFORCE:
            raise DirectApiPromotionError(
                "human access enforce mode requires a separately reviewed promotion"
            )
        revoke = request.action_type_name == REVOKE_HUMAN_ACCESS_ACTION
        if revoke and (
            self.replacement is None or "replacement_revisions" not in request.arguments
        ):
            raise DirectApiPreconditionError(
                "human access revocation requires a reviewed replacement-coverage case"
            )
        expected_keys = {"case_id", "expected_revision"}
        if revoke:
            expected_keys.add("replacement_revisions")
        if set(request.arguments) != expected_keys:
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
        if revoke:
            replacements = request.arguments["replacement_revisions"]
            if not isinstance(replacements, Mapping) or self.replacement is None:
                raise DirectApiPreconditionError("human access replacement revisions are required")
            if any(
                not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool)
                for key, value in replacements.items()
            ):
                raise DirectApiPreconditionError("human access replacement revision is invalid")
            try:
                plan = await self.replacement.plan(
                    case_id=case_id,
                    expected_revision=expected_revision,
                    replacement_revisions=replacements,
                )
            except ValueError as exc:
                raise DirectApiPreconditionError("replacement coverage did not verify") from exc
            return DirectApiReceipt(
                DirectApiOutcome.SUCCEEDED,
                f"human-access-revoke-plan:{plan.removal.target_digest}",
                detail="shadow replacement plan verified; no access or duty removed",
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
