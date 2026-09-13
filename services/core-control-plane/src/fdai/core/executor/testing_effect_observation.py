"""Process-local append-only observation store for tests and local runs.

The durable store is PostgreSQL.  This double exists so the ledger's state
machine can be exercised without a database while keeping the same
append-only contract: a retained receipt is never mutated, and a different
receipt may never reuse an occupied sequence position.
"""

from __future__ import annotations

import asyncio

from fdai.core.executor.effect_observation import (
    IndependentEffectObservationReceipt,
)
from fdai.core.executor.effect_observation_ledger import (
    IndependentEffectLedgerError,
)


class InMemoryIndependentEffectObservationStore:
    """Non-production append-only observation retention."""

    production_eligible = False

    def __init__(self) -> None:
        self._lineage: dict[str, list[IndependentEffectObservationReceipt]] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        receipt: IndependentEffectObservationReceipt,
    ) -> IndependentEffectObservationReceipt:
        """Append one receipt or return the identical retained receipt."""

        if type(receipt) is not IndependentEffectObservationReceipt:
            raise IndependentEffectLedgerError("observation store requires an exact receipt")
        async with self._lock:
            lineage = self._lineage.setdefault(
                receipt.binding.evidence_identity_digest,
                [],
            )
            if receipt.sequence <= len(lineage):
                retained = lineage[receipt.sequence - 1]
                if retained.receipt_digest != receipt.receipt_digest:
                    raise IndependentEffectLedgerError(
                        "a different observation already occupies this sequence"
                    )
                return retained
            if receipt.sequence != len(lineage) + 1:
                raise IndependentEffectLedgerError("observation sequence MUST be contiguous")
            expected_prior = lineage[-1].receipt_digest if lineage else None
            if receipt.prior_receipt_digest != expected_prior:
                raise IndependentEffectLedgerError("observation predecessor does not match")
            lineage.append(receipt)
            return receipt

    async def read_lineage(
        self,
        evidence_identity_digest: str,
    ) -> tuple[IndependentEffectObservationReceipt, ...]:
        """Return every retained receipt for one dispatch, in sequence order."""

        async with self._lock:
            return tuple(self._lineage.get(evidence_identity_digest, ()))


__all__ = ["InMemoryIndependentEffectObservationStore"]
