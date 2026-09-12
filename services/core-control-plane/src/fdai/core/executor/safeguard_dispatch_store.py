"""Durable safeguard dispatch evidence results and store seam."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Self, runtime_checkable

from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_identity import (
    SafeguardDispatchEvidenceIdentity,
)
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest,
    utc,
    validate_digest,
)
from fdai.core.executor.safeguard_dispatch_transition import (
    validate_dispatch_evidence_transition,
)
from fdai.shared.providers.resource_lock import LiveLockOwnershipAssessment


class SafeguardDispatchPersistenceDecision(StrEnum):
    """Atomic initial safeguard evidence persistence disposition."""

    PERSISTED = "persisted"
    DUPLICATE_SAME = "duplicate_same"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class SafeguardDispatchTransitionReceipt:
    """Exact-predecessor persistence and authoritative readback evidence."""

    schema_version: Literal["1.0.0"]
    prior_record: SafeguardDispatchEvidenceRecord | None
    record: SafeguardDispatchEvidenceRecord
    bundle_persistence_receipt: SafeguardDispatchTransitionReceipt | None
    current_lock_assessment: LiveLockOwnershipAssessment | None
    store_receipt_digest: str
    recorded_at: datetime
    receipt_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported safeguard dispatch transition receipt schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("safeguard dispatch transition receipt MUST NOT grant authority")
        if type(self.record) is not SafeguardDispatchEvidenceRecord:
            raise ValueError("safeguard dispatch transition receipt requires exact record")
        if self.prior_record is None:
            if (
                self.record.revision != 1
                or self.record.prior_record_digest is not None
                or self.record.state is not SafeguardDispatchEvidenceState.BUNDLE_PERSISTED
            ):
                raise ValueError("initial safeguard dispatch transition is invalid")
            if (
                self.bundle_persistence_receipt is not None
                or self.current_lock_assessment is not None
            ):
                raise ValueError("initial safeguard dispatch transition has prerequisites")
        else:
            if type(self.prior_record) is not SafeguardDispatchEvidenceRecord:
                raise ValueError("safeguard dispatch transition predecessor is invalid")
            validate_dispatch_evidence_transition(
                self.prior_record,
                self.record,
                current_lock_assessment=self.current_lock_assessment,
            )
            if self.record.state is SafeguardDispatchEvidenceState.DISPATCH_STARTED:
                prerequisite = self.bundle_persistence_receipt
                start = self.record.dispatch_start_checkpoint
                if (
                    type(prerequisite) is not SafeguardDispatchTransitionReceipt
                    or prerequisite.prior_record is not None
                    or prerequisite.record != self.prior_record
                    or start is None
                    or start.bundle_persistence_receipt_digest != prerequisite.receipt_digest
                ):
                    raise ValueError("dispatch-start transition lacks bundle persistence receipt")
            elif self.bundle_persistence_receipt is not None:
                raise ValueError("non-start transition has bundle persistence receipt")
        validate_digest("store_receipt_digest", self.store_receipt_digest)
        normalized_at = utc(self.recorded_at, "recorded_at")
        if normalized_at < self.record.state_changed_at or (
            self.prior_record is not None and normalized_at < self.prior_record.state_changed_at
        ):
            raise ValueError("safeguard dispatch transition receipt is backdated")
        validate_digest("receipt_digest", self.receipt_digest)
        if self.receipt_digest != payload_digest(
            asdict(self),
            "safeguard-dispatch-transition",
            digest_field="receipt_digest",
        ):
            raise ValueError("safeguard dispatch transition receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        prior_record: SafeguardDispatchEvidenceRecord | None,
        record: SafeguardDispatchEvidenceRecord,
        bundle_persistence_receipt: SafeguardDispatchTransitionReceipt | None = None,
        current_lock_assessment: LiveLockOwnershipAssessment | None = None,
        store_receipt_digest: str,
        recorded_at: datetime,
    ) -> Self:
        """Create evidence only after atomic persistence and exact readback."""

        if cls is not SafeguardDispatchTransitionReceipt:
            raise TypeError("safeguard dispatch transition receipt does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "prior_record": prior_record,
            "record": record,
            "bundle_persistence_receipt": bundle_persistence_receipt,
            "current_lock_assessment": current_lock_assessment,
            "store_receipt_digest": store_receipt_digest,
            "recorded_at": utc(recorded_at, "recorded_at"),
            "execution_authority": False,
            "effect_verified": False,
        }
        values["receipt_digest"] = payload_digest(
            values,
            "safeguard-dispatch-transition",
            digest_field="receipt_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SafeguardDispatchPersistenceResult:
    """Atomic insert result that separates persistence from observation."""

    candidate_identity: SafeguardDispatchEvidenceIdentity
    decision: SafeguardDispatchPersistenceDecision
    observed_record: SafeguardDispatchEvidenceRecord
    transition_receipt: SafeguardDispatchTransitionReceipt | None

    def __post_init__(self) -> None:
        if type(self.candidate_identity) is not SafeguardDispatchEvidenceIdentity:
            raise ValueError("safeguard dispatch persistence requires exact candidate")
        if type(self.decision) is not SafeguardDispatchPersistenceDecision:
            raise ValueError("safeguard dispatch persistence decision is invalid")
        if type(self.observed_record) is not SafeguardDispatchEvidenceRecord:
            raise ValueError("safeguard dispatch persistence requires exact observed record")
        if self.decision is SafeguardDispatchPersistenceDecision.PERSISTED:
            if (
                type(self.transition_receipt) is not SafeguardDispatchTransitionReceipt
                or self.transition_receipt.prior_record is not None
                or self.transition_receipt.record != self.observed_record
                or self.observed_record.identity != self.candidate_identity
            ):
                raise ValueError("persisted safeguard dispatch evidence requires insert receipt")
        else:
            if self.transition_receipt is not None:
                raise ValueError("observed safeguard dispatch evidence MUST NOT claim persistence")
            expected = classify_safeguard_dispatch_evidence(
                self.observed_record,
                self.candidate_identity,
            )
            if self.decision is not expected:
                raise ValueError("safeguard dispatch persistence result mismatched candidate")


@dataclass(frozen=True, slots=True)
class SafeguardDispatchEvidenceReadback:
    """Authoritative current evidence record and persistence time."""

    record: SafeguardDispatchEvidenceRecord
    recorded_at: datetime


@runtime_checkable
class SafeguardDispatchEvidenceStore(Protocol):
    """Atomic initial persistence, exact CAS, and authoritative readback seam."""

    async def persist_bundle(
        self,
        record: SafeguardDispatchEvidenceRecord,
    ) -> SafeguardDispatchPersistenceResult:
        """Persist revision one or return duplicate/conflict observation."""
        ...

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: SafeguardDispatchEvidenceRecord,
        bundle_persistence_receipt: SafeguardDispatchTransitionReceipt | None = None,
        current_lock_assessment: LiveLockOwnershipAssessment | None = None,
    ) -> SafeguardDispatchTransitionReceipt:
        """Atomically replace the exact prior record and read it back."""
        ...

    async def read(
        self,
        target_digest: str,
        generation: int,
    ) -> SafeguardDispatchEvidenceRecord | None:
        """Read the authoritative evidence for one target-fence generation."""
        ...

    async def read_with_timestamp(
        self,
        target_digest: str,
        generation: int,
    ) -> SafeguardDispatchEvidenceReadback | None:
        """Read authoritative evidence with its persistence time."""
        ...


def classify_safeguard_dispatch_evidence(
    existing: SafeguardDispatchEvidenceRecord,
    candidate: SafeguardDispatchEvidenceIdentity,
) -> SafeguardDispatchPersistenceDecision:
    """Classify an existing generation without granting execution authority."""

    if (
        existing.identity.target_digest != candidate.target_digest
        or existing.identity.target_fence_generation != candidate.target_fence_generation
    ):
        raise ValueError("safeguard dispatch persistence key mismatched")
    if existing.identity.identity_digest == candidate.identity_digest:
        return SafeguardDispatchPersistenceDecision.DUPLICATE_SAME
    return SafeguardDispatchPersistenceDecision.CONFLICT


__all__ = [
    "SafeguardDispatchEvidenceReadback",
    "SafeguardDispatchEvidenceStore",
    "SafeguardDispatchPersistenceDecision",
    "SafeguardDispatchPersistenceResult",
    "SafeguardDispatchTransitionReceipt",
    "classify_safeguard_dispatch_evidence",
]
