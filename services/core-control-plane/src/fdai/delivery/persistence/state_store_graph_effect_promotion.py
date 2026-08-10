"""StateStore persistence for immutable graph effect promotion receipts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fdai.core.measurement.graph_effect_promotion import GraphEffectModelPromotionReceipt
from fdai.shared.providers.state_store import StateStore

_PREFIX = "graph-effect-model-promotion-receipt:"


class StateStoreGraphEffectModelPromotionReceiptStore:
    """Persist and load exact-key immutable graph-model promotion evidence."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def store(
        self,
        receipt: GraphEffectModelPromotionReceipt,
        *,
        producer_principal: str = "Norns",
    ) -> bool:
        if not producer_principal:
            raise ValueError("graph model promotion producer principal MUST be non-empty")
        key = _key(receipt)
        created = await self._store.write_state_with_audit_if_absent(
            key,
            receipt.as_json(),
            {
                "actor": producer_principal,
                "producer_principal": producer_principal,
                "action_kind": "graph_effect_model.promotion_receipt_recorded",
                "mode": "shadow",
                "model_ref": receipt.model_ref,
                "receipt_digest": receipt.receipt_digest,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
                "grants_authority": False,
            },
        )
        if created:
            return True
        existing = await self._store.read_state(key)
        if existing is None:
            raise RuntimeError("graph model promotion receipt disappeared after collision")
        if GraphEffectModelPromotionReceipt.from_json(dict(existing)) != receipt:
            raise ValueError("graph model promotion receipt identity collision")
        return False

    async def load(
        self,
        *,
        model_ref: str,
        fdai_revision: str,
        scenario_set_version: str,
        receipt_digest: str,
    ) -> GraphEffectModelPromotionReceipt | None:
        raw = await self._store.read_state(
            _key_parts(
                model_ref=model_ref,
                fdai_revision=fdai_revision,
                scenario_set_version=scenario_set_version,
                receipt_digest=receipt_digest,
            )
        )
        return GraphEffectModelPromotionReceipt.from_json(dict(raw)) if raw is not None else None


def _key(receipt: GraphEffectModelPromotionReceipt) -> str:
    return _key_parts(
        model_ref=receipt.model_ref,
        fdai_revision=receipt.fdai_revision,
        scenario_set_version=receipt.scenario_set_version,
        receipt_digest=receipt.receipt_digest,
    )


def _key_parts(
    *,
    model_ref: str,
    fdai_revision: str,
    scenario_set_version: str,
    receipt_digest: str,
) -> str:
    identity = "\0".join((model_ref, fdai_revision, scenario_set_version, receipt_digest)).encode(
        "utf-8"
    )
    return f"{_PREFIX}{hashlib.sha256(identity).hexdigest()}"


__all__ = ["StateStoreGraphEffectModelPromotionReceiptStore"]
