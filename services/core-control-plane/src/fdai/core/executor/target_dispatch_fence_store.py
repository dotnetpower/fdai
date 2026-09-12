"""Target dispatch fence acquisition results and durable store seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceIdentity,
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    TargetDispatchFenceTransitionReceipt,
)


class TargetDispatchFenceAcquireDecision(StrEnum):
    """Atomic target-generation acquisition disposition."""

    ACQUIRED = "acquired"
    DUPLICATE_SAME = "duplicate_same"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class TargetDispatchFenceAcquireResult:
    """Atomic target-generation acquisition result."""

    candidate_identity: TargetDispatchFenceIdentity
    decision: TargetDispatchFenceAcquireDecision
    observed_record: TargetDispatchFenceRecord
    transition_receipt: TargetDispatchFenceTransitionReceipt | None

    def __post_init__(self) -> None:
        if type(self.candidate_identity) is not TargetDispatchFenceIdentity:
            raise ValueError("target dispatch fence result requires an exact candidate")
        if type(self.decision) is not TargetDispatchFenceAcquireDecision:
            raise ValueError("target dispatch fence acquire decision is invalid")
        if type(self.observed_record) is not TargetDispatchFenceRecord:
            raise ValueError("target dispatch fence result requires an exact record")
        if self.decision is TargetDispatchFenceAcquireDecision.ACQUIRED:
            if (
                type(self.transition_receipt) is not TargetDispatchFenceTransitionReceipt
                or self.transition_receipt.record != self.observed_record
                or self.observed_record.identity != self.candidate_identity
                or self.observed_record.state is not TargetDispatchFenceState.PREPARING
            ):
                raise ValueError("acquired target dispatch fence requires exact insert evidence")
        else:
            if self.transition_receipt is not None:
                raise ValueError("observed target dispatch fence MUST NOT claim insert evidence")
            expected = classify_target_fence(
                self.observed_record,
                self.candidate_identity,
            )
            if self.decision is not expected:
                raise ValueError("target dispatch fence result mismatched candidate")


@dataclass(frozen=True, slots=True)
class TargetDispatchFenceReadback:
    """Authoritative current fence record and persistence time."""

    record: TargetDispatchFenceRecord
    recorded_at: datetime


@runtime_checkable
class TargetDispatchFenceStore(Protocol):
    """Atomic target-unique insert, CAS transition, and readback seam."""

    async def acquire_generation(
        self,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceAcquireResult:
        """Insert one preparing generation or return duplicate/blocked state."""
        ...

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: TargetDispatchFenceRecord,
    ) -> TargetDispatchFenceTransitionReceipt:
        """Replace the exact target record and authoritatively read it back."""
        ...

    async def read(
        self,
        target_digest: str,
    ) -> TargetDispatchFenceRecord | None:
        """Return the authoritative current generation for one target."""
        ...

    async def read_with_timestamp(
        self,
        target_digest: str,
    ) -> TargetDispatchFenceReadback | None:
        """Return the current generation with authoritative persistence time."""
        ...


def classify_target_fence(
    existing: TargetDispatchFenceRecord,
    candidate: TargetDispatchFenceIdentity,
) -> TargetDispatchFenceAcquireDecision:
    """Classify one candidate without granting sink-dispatch authority."""

    if existing.identity.target_digest != candidate.target_digest:
        raise ValueError("target dispatch fence classifier target mismatched")
    if existing.identity.identity_digest == candidate.identity_digest:
        return TargetDispatchFenceAcquireDecision.DUPLICATE_SAME
    return TargetDispatchFenceAcquireDecision.BLOCKED


def target_mutation_blocked(record: TargetDispatchFenceRecord | None) -> bool:
    """Block every target mutation until the current generation is resolved."""

    return bool(record is not None and record.state is not TargetDispatchFenceState.RESOLVED)


__all__ = [
    "TargetDispatchFenceAcquireDecision",
    "TargetDispatchFenceAcquireResult",
    "TargetDispatchFenceReadback",
    "TargetDispatchFenceStore",
    "classify_target_fence",
    "target_mutation_blocked",
]
