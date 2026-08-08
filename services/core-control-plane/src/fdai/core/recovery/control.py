"""Pre-authorized recovery control over an injected Thor execution boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.core.recovery.models import RecoveryAction, RecoveryPlanRecord
from fdai.core.recovery.readiness import preauthorization_covers


@runtime_checkable
class RecoveryActionDispatcher(Protocol):
    async def dispatch(
        self,
        action: RecoveryAction,
        *,
        idempotency_key: str,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class RecoveryControlResult:
    plan_id: str
    succeeded: bool
    receipts: tuple[str, ...]
    failed_action_id: str | None = None
    reason: str | None = None


class PreauthorizedRecoveryController:
    def __init__(self, *, dispatcher: RecoveryActionDispatcher) -> None:
        self._dispatcher = dispatcher

    async def execute(
        self,
        plan: RecoveryPlanRecord,
        *,
        target_ids: tuple[str, ...],
        now: datetime,
        destructive: bool = False,
    ) -> RecoveryControlResult:
        versions = tuple((item.action_type_ref, item.action_type_version) for item in plan.actions)
        if not preauthorization_covers(
            plan,
            target_ids=target_ids,
            action_versions=versions,
            now=now,
            destructive=destructive,
        ):
            return RecoveryControlResult(
                plan_id=plan.plan_id,
                succeeded=False,
                receipts=(),
                reason="recovery request exceeds pre-authorized scope",
            )
        by_id = {item.action_id: item for item in plan.actions}
        receipts: list[str] = []
        for action_id in plan.compensation_order:
            action = by_id[action_id]
            try:
                receipt = await self._dispatcher.dispatch(
                    action,
                    idempotency_key=f"{plan.plan_id}:compensate:{action_id}",
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
                return RecoveryControlResult(
                    plan_id=plan.plan_id,
                    succeeded=False,
                    receipts=tuple(receipts),
                    failed_action_id=action_id,
                    reason=f"recovery dispatcher failed: {type(exc).__name__}",
                )
            if not receipt:
                return RecoveryControlResult(
                    plan_id=plan.plan_id,
                    succeeded=False,
                    receipts=tuple(receipts),
                    failed_action_id=action_id,
                    reason="recovery dispatcher returned no receipt",
                )
            receipts.append(receipt)
        return RecoveryControlResult(
            plan_id=plan.plan_id,
            succeeded=True,
            receipts=tuple(receipts),
        )


__all__ = [
    "PreauthorizedRecoveryController",
    "RecoveryActionDispatcher",
    "RecoveryControlResult",
]
