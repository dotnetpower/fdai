"""Thor-owned direct adapter for applying an approved ActionType promotion receipt."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.risk_gate import ActionModeRecord, PromotionMetrics
from fdai.shared.contracts.models import Mode, OntologyActionType
from fdai.shared.providers.direct_api import (
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)

PROMOTION_ACTION_TYPE = "governance.promote-action-type"


class OperationalPromotionReceiptReader(Protocol):
    async def load(
        self,
        *,
        action_type_name: str,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
    ) -> OperationalPromotionReceipt | None: ...


class PersistedActionPromotionRegistry(Protocol):
    def consider_promotion(
        self,
        *,
        action_type: OntologyActionType,
        metrics: PromotionMetrics,
        receipt: OperationalPromotionReceipt | None = None,
    ) -> ActionModeRecord: ...

    async def persist(self, action_type: str) -> None: ...


class OperationalPromotionDirectApiExecutor(DirectApiExecutor):
    """Apply one exact, measured receipt after the ordinary HIL gate."""

    def __init__(
        self,
        *,
        action_types: Mapping[str, OntologyActionType],
        receipts: OperationalPromotionReceiptReader,
        registry: PersistedActionPromotionRegistry,
    ) -> None:
        self._action_types = dict(action_types)
        self._receipts = receipts
        self._registry = registry

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name != PROMOTION_ACTION_TYPE:
            raise DirectApiPreconditionError("unsupported promotion action type")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError("promotion authority requires the enforce label")
        args = _promotion_arguments(request.arguments)
        target = self._action_types.get(args["action_type_id"])
        if target is None:
            raise DirectApiPreconditionError("promotion target ActionType is not registered")
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"shadow:promotion:{target.name}",
                detail="shadow: exact promotion receipt was not applied",
            )
        receipt = await self._receipts.load(
            action_type_name=target.name,
            fdai_revision=args["fdai_revision"],
            scenario_set_version=args["scenario_set_version"],
            evidence_digest=args["evidence_digest"],
        )
        if receipt is None:
            raise DirectApiPreconditionError("exact operational promotion receipt was not found")
        if (
            receipt.action_type_name != target.name
            or receipt.fdai_revision != args["fdai_revision"]
            or receipt.scenario_set_version != args["scenario_set_version"]
            or receipt.evidence_digest != args["evidence_digest"]
        ):
            raise DirectApiPreconditionError("operational promotion receipt identity mismatched")
        if not receipt.ready:
            raise DirectApiPreconditionError("operational promotion receipt is not ready")
        metrics = PromotionMetrics(
            action_type=target.name,
            shadow_days=receipt.live_observation_days,
            samples=receipt.sample_count,
            accuracy=receipt.accuracy,
            policy_escapes=receipt.policy_escapes,
        )
        record = self._registry.consider_promotion(
            action_type=target,
            metrics=metrics,
            receipt=receipt,
        )
        if record.mode is not Mode.ENFORCE:
            raise DirectApiPreconditionError("operational promotion receipt was rejected")
        await self._registry.persist(target.name)
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"promotion:{target.name}:{receipt.evidence_digest}",
            detail="verified operational promotion receipt applied",
        )


def _promotion_arguments(arguments: Mapping[str, object]) -> dict[str, str]:
    required = (
        "action_type_id",
        "fdai_revision",
        "scenario_set_version",
        "evidence_digest",
    )
    values: dict[str, str] = {}
    for name in required:
        value = arguments.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DirectApiPreconditionError(f"promotion argument {name} is required")
        values[name] = value
    if arguments.get("target_mode") != Mode.ENFORCE.value:
        raise DirectApiPreconditionError("promotion target_mode MUST be enforce")
    return values


__all__ = [
    "OperationalPromotionDirectApiExecutor",
    "OperationalPromotionReceiptReader",
    "PROMOTION_ACTION_TYPE",
    "PersistedActionPromotionRegistry",
]
