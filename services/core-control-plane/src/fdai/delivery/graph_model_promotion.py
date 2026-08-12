"""Direct adapter for Owner-HIL-governed GraphEffectModel pointer changes."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Protocol

from fdai.core.assurance_twin.model_promotion import GraphModelPromotionReceipt
from fdai.delivery.persistence.state_store_graph_model_promotion import GraphModelPointerUpdate
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
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_TIMEOUT_SECONDS = 2.0
_REGISTRY_TIMEOUT_SECONDS = 2.0
_TOTAL_TIMEOUT_SECONDS = 5.0


class GraphModelPromotionRegistry(Protocol):
    """Persistence operations available to the governed direct adapter."""

    async def load_receipt(self, receipt_digest: str) -> GraphModelPromotionReceipt | None: ...

    async def promote(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        actor: str,
    ) -> GraphModelPointerUpdate: ...

    async def rollback(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        actor: str,
    ) -> GraphModelPointerUpdate: ...


class GraphModelPromotionDirectApiExecutor(DirectApiExecutor):
    """Apply one exact model receipt only after the ordinary governed execution path."""

    def __init__(self, *, registry: GraphModelPromotionRegistry) -> None:
        self._registry = registry

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        """Validate shadow requests or atomically promote/rollback within five seconds."""

        try:
            async with asyncio.timeout(_TOTAL_TIMEOUT_SECONDS):
                return await self._execute_bounded(request)
        except TimeoutError as exc:
            raise DirectApiPreconditionError(
                "graph model promotion exceeded its 5 second adapter budget"
            ) from exc

    async def _execute_bounded(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name != PROMOTE_EFFECT_MODEL_ACTION_TYPE:
            raise DirectApiPreconditionError("unsupported graph model promotion ActionType")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError("graph model promotion requires the enforce label")
        arguments = _arguments(request.arguments)
        try:
            async with asyncio.timeout(_RECEIPT_TIMEOUT_SECONDS):
                receipt = await self._registry.load_receipt(arguments["receipt_digest"])
        except TimeoutError as exc:
            raise DirectApiPreconditionError(
                "graph model promotion receipt load exceeded 2 seconds"
            ) from exc
        if receipt is None:
            raise DirectApiPreconditionError("exact graph model promotion receipt was not found")
        if receipt.slot_digest != arguments["slot_digest"]:
            raise DirectApiPreconditionError("graph model promotion receipt slot mismatched")
        expected_resource_ref = f"graph-effect-model-slot:{receipt.slot_digest}"
        if request.resource_ref != expected_resource_ref:
            raise DirectApiPreconditionError("graph model promotion target resource mismatched")
        transition = arguments["transition"]
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"shadow:graph-model-promotion:{receipt.content_digest}",
                detail=f"shadow: exact graph model {transition} receipt was not applied",
            )
        try:
            async with asyncio.timeout(_REGISTRY_TIMEOUT_SECONDS):
                update = (
                    await self._registry.promote(receipt, actor="Thor")
                    if transition == "promote"
                    else await self._registry.rollback(receipt, actor="Thor")
                )
        except TimeoutError as exc:
            raise DirectApiPreconditionError(
                "graph model promotion registry CAS exceeded 2 seconds"
            ) from exc
        except ValueError as exc:
            raise DirectApiPreconditionError(str(exc)) from exc
        return DirectApiReceipt(
            outcome=(
                DirectApiOutcome.SUCCEEDED if update.applied else DirectApiOutcome.ALREADY_APPLIED
            ),
            receipt_ref=(
                f"graph-model-{transition}:{receipt.slot_digest}:r{update.pointer.revision}"
            ),
            already_existed=not update.applied,
            detail=f"verified graph model {update.reason}",
        )


def _arguments(arguments: Mapping[str, object]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in ("receipt_digest", "slot_digest", "transition"):
        value = arguments.get(field)
        if not isinstance(value, str) or not value:
            raise DirectApiPreconditionError(f"graph model promotion argument {field} is required")
        values[field] = value
    if _DIGEST.fullmatch(values["receipt_digest"]) is None:
        raise DirectApiPreconditionError("graph model promotion receipt_digest MUST be SHA-256")
    if _DIGEST.fullmatch(values["slot_digest"]) is None:
        raise DirectApiPreconditionError("graph model promotion slot_digest MUST be SHA-256")
    if values["transition"] not in {"promote", "rollback"}:
        raise DirectApiPreconditionError(
            "graph model promotion transition MUST be promote or rollback"
        )
    return values


__all__ = [
    "GraphModelPromotionDirectApiExecutor",
    "GraphModelPromotionRegistry",
    "PROMOTE_EFFECT_MODEL_ACTION_TYPE",
]
