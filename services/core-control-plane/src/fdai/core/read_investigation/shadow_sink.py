"""Append-only persistence seam for read-investigation shadow receipts."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.read_investigation.resource_state_shadow_models import (
        ShadowComparisonReceipt,
    )


@runtime_checkable
class ShadowComparisonSink(Protocol):
    """Persist one immutable receipt without receiving response authority."""

    async def append(self, receipt: ShadowComparisonReceipt) -> None:
        """Append or idempotently retain one content-addressed receipt."""


class InMemoryShadowComparisonSink:
    """Concurrency-safe append-only sink for focused tests."""

    def __init__(self) -> None:
        self._records: dict[str, ShadowComparisonReceipt] = {}
        self._lock = asyncio.Lock()

    async def append(self, receipt: ShadowComparisonReceipt) -> None:
        """Append a receipt, treating the same comparison identity as a replay."""

        async with self._lock:
            existing = self._records.get(receipt.receipt_digest)
            if existing is not None:
                if existing.model_dump(exclude={"attempt_latency_ms"}) != receipt.model_dump(
                    exclude={"attempt_latency_ms"}
                ):
                    raise ValueError("shadow comparison receipt digest collision")
                return
            self._records[receipt.receipt_digest] = receipt

    async def list_receipts(self) -> tuple[ShadowComparisonReceipt, ...]:
        """Return receipts in deterministic digest order."""

        async with self._lock:
            return tuple(self._records[key] for key in sorted(self._records))


__all__ = ["InMemoryShadowComparisonSink", "ShadowComparisonSink"]
