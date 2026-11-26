"""Append-only persistence seam for read-investigation shadow receipts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.core.read_investigation.resource_state_shadow_models import (
    ShadowComparisonReceipt,
    ShadowReceiptPersistence,
)
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "read-investigation-shadow:"


class ShadowReceiptIdentityConflictError(ValueError):
    """A persisted shadow identity was reused for different immutable content."""


@dataclass(frozen=True, slots=True)
class ShadowSinkAppendResult:
    """The exact immutable record retained by an append operation."""

    receipt: ShadowComparisonReceipt
    persistence: ShadowReceiptPersistence

    def __post_init__(self) -> None:
        if self.persistence not in {
            ShadowReceiptPersistence.RECORDED,
            ShadowReceiptPersistence.RETAINED,
        }:
            raise ValueError("successful shadow sink result MUST be recorded or retained")


@runtime_checkable
class ShadowComparisonSink(Protocol):
    """Persist one immutable receipt without receiving response authority."""

    async def append(self, receipt: ShadowComparisonReceipt) -> ShadowSinkAppendResult:
        """Append or idempotently return the exact retained receipt."""


class InMemoryShadowComparisonSink:
    """Concurrency-safe append-only sink for focused tests."""

    def __init__(self) -> None:
        self._records: dict[str, ShadowComparisonReceipt] = {}
        self._lock = asyncio.Lock()

    async def append(self, receipt: ShadowComparisonReceipt) -> ShadowSinkAppendResult:
        """Append a receipt, treating the same comparison identity as a replay."""

        async with self._lock:
            existing = self._records.get(receipt.receipt_digest)
            if existing is not None:
                if existing != receipt:
                    raise ShadowReceiptIdentityConflictError(
                        "shadow comparison receipt identity conflicts with retained content"
                    )
                return ShadowSinkAppendResult(
                    receipt=existing,
                    persistence=ShadowReceiptPersistence.RETAINED,
                )
            self._records[receipt.receipt_digest] = receipt
            return ShadowSinkAppendResult(
                receipt=receipt,
                persistence=ShadowReceiptPersistence.RECORDED,
            )

    async def list_receipts(self) -> tuple[ShadowComparisonReceipt, ...]:
        """Return receipts in deterministic digest order."""

        async with self._lock:
            return tuple(self._records[key] for key in sorted(self._records))


class StateStoreShadowComparisonSink:
    """Append immutable shadow receipts through the durable StateStore seam."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def append(self, receipt: ShadowComparisonReceipt) -> ShadowSinkAppendResult:
        """Create one digest-keyed record or return its exact retained replay."""

        key = f"{_STATE_PREFIX}{receipt.receipt_digest}"
        value = {
            "record_type": "read_investigation.resource_state_shadow.v1",
            "receipt": receipt.model_dump(mode="json"),
        }
        if await self._store.write_state_if_absent(key, value):
            return ShadowSinkAppendResult(
                receipt=receipt,
                persistence=ShadowReceiptPersistence.RECORDED,
            )
        retained = await self._store.read_state(key)
        if retained is None or retained.get("record_type") != value["record_type"]:
            raise ShadowReceiptIdentityConflictError(
                "shadow comparison receipt identity has invalid retained state"
            )
        try:
            decoded = ShadowComparisonReceipt.model_validate(retained.get("receipt"))
        except (TypeError, ValueError) as exc:
            raise ShadowReceiptIdentityConflictError(
                "shadow comparison receipt identity has malformed retained content"
            ) from exc
        if decoded != receipt:
            raise ShadowReceiptIdentityConflictError(
                "shadow comparison receipt identity conflicts with retained content"
            )
        return ShadowSinkAppendResult(
            receipt=decoded,
            persistence=ShadowReceiptPersistence.RETAINED,
        )


__all__ = [
    "InMemoryShadowComparisonSink",
    "StateStoreShadowComparisonSink",
    "ShadowComparisonSink",
    "ShadowReceiptIdentityConflictError",
    "ShadowSinkAppendResult",
]
