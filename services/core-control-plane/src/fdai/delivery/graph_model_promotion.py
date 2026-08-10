"""Thor-owned direct adapter for governed graph-model promotion and rollback."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.assurance_twin.graph_model_lifecycle import (
    StateStoreGraphEffectModelLifecycleRegistry,
)
from fdai.core.measurement.graph_effect_promotion import GraphEffectModelPromotionReceipt
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)

PROMOTE_EFFECT_MODEL_ACTION_TYPE = "governance.promote-effect-model"
DEMOTE_EFFECT_MODEL_ACTION_TYPE = "governance.demote-effect-model"


class GraphEffectModelPromotionReceiptReader(Protocol):
    async def load(
        self,
        *,
        model_ref: str,
        fdai_revision: str,
        scenario_set_version: str,
        receipt_digest: str,
    ) -> GraphEffectModelPromotionReceipt | None: ...


class GraphEffectModelPromotionDirectApiExecutor(DirectApiExecutor):
    """Apply an exact receipt after the ordinary Owner HIL and Thor gates."""

    def __init__(
        self,
        *,
        receipts: GraphEffectModelPromotionReceiptReader,
        lifecycle: StateStoreGraphEffectModelLifecycleRegistry,
    ) -> None:
        self._receipts = receipts
        self._lifecycle = lifecycle

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name not in {
            PROMOTE_EFFECT_MODEL_ACTION_TYPE,
            DEMOTE_EFFECT_MODEL_ACTION_TYPE,
        }:
            raise DirectApiPreconditionError("unsupported graph model governance action")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError("graph model governance authority requires enforce label")
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"shadow:graph-model-governance:{request.action_type_name}",
                detail="shadow: graph model lifecycle state was not changed",
            )
        if request.action_type_name == PROMOTE_EFFECT_MODEL_ACTION_TYPE:
            return await self._promote(request.arguments)
        return await self._demote(request.arguments)

    async def _promote(self, arguments: Mapping[str, object]) -> DirectApiReceipt:
        values = _required_arguments(
            arguments,
            ("model_ref", "fdai_revision", "scenario_set_version", "receipt_digest"),
        )
        receipt = await self._receipts.load(
            model_ref=values["model_ref"],
            fdai_revision=values["fdai_revision"],
            scenario_set_version=values["scenario_set_version"],
            receipt_digest=values["receipt_digest"],
        )
        if receipt is None:
            raise DirectApiPreconditionError("exact graph model promotion receipt was not found")
        if (
            receipt.model_ref != values["model_ref"]
            or receipt.fdai_revision != values["fdai_revision"]
            or receipt.scenario_set_version != values["scenario_set_version"]
            or receipt.receipt_digest != values["receipt_digest"]
            or not receipt.ready
        ):
            raise DirectApiPreconditionError(
                "graph model promotion receipt is mismatched or unready"
            )
        record = await self._lifecycle.promote(
            receipt=receipt,
            actor="Thor",
            promoted_at=datetime.now(tz=UTC),
        )
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"graph-model-promotion:{record.scope_digest}:{receipt.receipt_digest}",
            detail="verified graph model promotion receipt applied",
        )

    async def _demote(self, arguments: Mapping[str, object]) -> DirectApiReceipt:
        values = _required_arguments(
            arguments,
            ("scope_digest", "expected_active_ref", "promotion_receipt_digest"),
        )
        record = await self._lifecycle.rollback(
            scope_digest=values["scope_digest"],
            expected_active_ref=values["expected_active_ref"],
            promotion_receipt_digest=values["promotion_receipt_digest"],
            actor="Thor",
            rolled_back_at=datetime.now(tz=UTC),
        )
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"graph-model-rollback:{record.scope_digest}:r{record.revision}",
            detail="graph model active pointer restored to retained rollback target",
        )


def _required_arguments(
    arguments: Mapping[str, object],
    required: tuple[str, ...],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in required:
        value = arguments.get(name)
        if not isinstance(value, str) or not value:
            raise DirectApiPreconditionError(f"graph model governance argument {name} is required")
        values[name] = value
    return values


__all__ = [
    "DEMOTE_EFFECT_MODEL_ACTION_TYPE",
    "GraphEffectModelPromotionDirectApiExecutor",
    "GraphEffectModelPromotionReceiptReader",
    "PROMOTE_EFFECT_MODEL_ACTION_TYPE",
]
