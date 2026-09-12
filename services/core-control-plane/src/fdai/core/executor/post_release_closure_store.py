"""Durable post-release closure store receipt and provider seam."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Self, runtime_checkable

from fdai.core.executor.post_release_closure import PostReleaseClosureRecord
from fdai.core.executor.post_release_closure_plan import PostReleaseClosurePlan
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest,
    utc,
    validate_digest,
)


class PostReleaseClosureWriteDecision(StrEnum):
    """Whether the exact closure revision was applied or already durable."""

    APPLIED = "applied"
    DUPLICATE_SAME = "duplicate_same"


@dataclass(frozen=True, slots=True)
class PostReleaseClosureStoreReceipt:
    """Authoritative exact-readback evidence for one atomic closure write."""

    schema_version: Literal["1.0.0"]
    decision: PostReleaseClosureWriteDecision
    record: PostReleaseClosureRecord
    persisted_at: datetime
    read_back_at: datetime
    store_receipt_digest: str
    receipt_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported post-release closure store receipt schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("post-release closure store receipt MUST NOT grant authority")
        if type(self.decision) is not PostReleaseClosureWriteDecision:
            raise ValueError("post-release closure write decision is invalid")
        if type(self.record) is not PostReleaseClosureRecord:
            raise ValueError("post-release closure store receipt requires exact record")
        normalized_persisted_at = utc(self.persisted_at, "persisted_at")
        normalized_read_back_at = utc(self.read_back_at, "read_back_at")
        if (
            normalized_persisted_at < self.record.closed_at
            or normalized_read_back_at < normalized_persisted_at
        ):
            raise ValueError("post-release closure store receipt chronology is invalid")
        validate_digest("store_receipt_digest", self.store_receipt_digest)
        validate_digest("receipt_digest", self.receipt_digest)
        if self.receipt_digest != payload_digest(
            asdict(self),
            "post-release-closure-store-receipt",
            digest_field="receipt_digest",
        ):
            raise ValueError("post-release closure store receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        decision: PostReleaseClosureWriteDecision,
        record: PostReleaseClosureRecord,
        persisted_at: datetime,
        read_back_at: datetime,
        store_receipt_digest: str,
    ) -> Self:
        """Create evidence only after atomic persistence and exact readback."""

        if cls is not PostReleaseClosureStoreReceipt:
            raise TypeError("post-release closure store receipt does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "decision": decision,
            "record": record,
            "persisted_at": utc(persisted_at, "persisted_at"),
            "read_back_at": utc(read_back_at, "read_back_at"),
            "store_receipt_digest": store_receipt_digest,
            "execution_authority": False,
            "effect_verified": False,
        }
        values["receipt_digest"] = payload_digest(
            values,
            "post-release-closure-store-receipt",
            digest_field="receipt_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@runtime_checkable
class PostReleaseClosureStore(Protocol):
    """One-transaction closure, reconciliation, and authoritative readback seam."""

    async def write(
        self,
        plan: PostReleaseClosurePlan,
    ) -> PostReleaseClosureStoreReceipt:
        """Apply one exact plan or return duplicate-same readback evidence."""
        ...

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        """Read the current durable closure revision by stable attempt key."""
        ...

    async def read_receipt(
        self,
        closure_key: str,
    ) -> PostReleaseClosureStoreReceipt | None:
        """Return authoritative readback evidence for the current closure."""
        ...


__all__ = [
    "PostReleaseClosureStore",
    "PostReleaseClosureStoreReceipt",
    "PostReleaseClosureWriteDecision",
]
