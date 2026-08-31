"""Retention-bounded analyzer finding receipt persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fdai.delivery.analyzer_tick import AnalyzerFindingReceipt
from fdai.shared.providers.state_store import StateStore

ANALYZER_RECEIPT_STATE_PREFIX = "runtime:analyzer-finding-receipt:"
DEFAULT_ANALYZER_RECEIPT_RETENTION = 500


@dataclass(frozen=True, slots=True)
class StateStoreAnalyzerReceiptStore:
    """Persist idempotent, presentation-safe receipts in tracked state."""

    state_store: StateStore
    retain_newest: int = DEFAULT_ANALYZER_RECEIPT_RETENTION

    def __post_init__(self) -> None:
        if not 1 <= self.retain_newest <= 10_000:
            raise ValueError("analyzer receipt retention MUST be in [1, 10000]")

    async def record(self, receipt: AnalyzerFindingReceipt) -> None:
        """Upsert one outcome and trim only older receipt projections."""
        identity = f"{receipt.idempotency_key}\n{receipt.publication.value}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        await self.state_store.write_state(
            f"{ANALYZER_RECEIPT_STATE_PREFIX}{digest}",
            receipt.to_dict(),
        )
        await self.state_store.delete_states_beyond(
            ANALYZER_RECEIPT_STATE_PREFIX,
            retain_newest=self.retain_newest,
        )


__all__ = [
    "ANALYZER_RECEIPT_STATE_PREFIX",
    "DEFAULT_ANALYZER_RECEIPT_RETENTION",
    "StateStoreAnalyzerReceiptStore",
]
