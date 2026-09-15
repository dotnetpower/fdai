"""Bounded no-authority receipt for one analyzer finding publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnalyzerPublicationStatus(StrEnum):
    """Terminal publication state for one analyzer finding."""

    PUBLISHED = "published"
    PUBLISHED_RECEIPT_UNRECORDED = "published_receipt_unrecorded"
    DUPLICATE_SUPPRESSED = "duplicate_suppressed"
    RECONCILED_DUPLICATE = "reconciled_duplicate"
    UNCERTAIN = "publish_uncertain"
    AWAITING_RECONCILIATION = "awaiting_reconciliation"
    FAILED = "failed"


class AnalyzerEvidenceState(StrEnum):
    """Completeness classification exposed by the bounded finding receipt."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    CONFLICTING = "conflicting"
    MISSED = "missed"


@dataclass(frozen=True, slots=True)
class AnalyzerFindingReceipt:
    """Join timing, evidence, publication, and recovery for one finding.

    ``evidence_complete`` and ``recovery_closed`` are copied from the typed
    assessment a canonical reducer produced. A finding without one carries no
    completeness or recovery claim at all, because a receipt that inferred one
    from free-form analyzer text would report a conclusion nothing verified.

    The receipt also carries the finding's own identity and observation time.
    A downstream projection needs to say *which* target a conclusion is about
    and *when* it was observed; deriving either from the idempotency key would
    re-parse a delivery detail into an operator-facing fact.
    """

    idempotency_key: str
    signal: str
    detection_latency_seconds: float
    evidence_complete: bool
    publication: AnalyzerPublicationStatus
    recovery_closed: bool | None
    evidence_refs: tuple[str, ...]
    resource_ref: str
    resource_kind: str
    occurred_at: datetime
    assessed_by: str | None = None
    recovery_status: str | None = None
    evidence_gaps: tuple[str, ...] = ()
    recorded_at: datetime | None = None
    current_state: str = "unknown"
    evidence_state: AnalyzerEvidenceState | None = None
    cause_claim_supported: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        for field_name, maximum in (
            ("idempotency_key", 1024),
            ("resource_ref", 512),
            ("resource_kind", 128),
            ("signal", 128),
            ("current_state", 128),
        ):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"AnalyzerFindingReceipt.{field_name} MUST be bounded text")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("AnalyzerFindingReceipt.occurred_at MUST be timezone-aware")
        if self.recorded_at is not None and (
            self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None
        ):
            raise ValueError("AnalyzerFindingReceipt.recorded_at MUST be timezone-aware")
        if self.detection_latency_seconds < 0:
            raise ValueError("AnalyzerFindingReceipt latency MUST be non-negative")
        if (
            len(self.evidence_refs) > 128
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(not item or len(item) > 512 for item in self.evidence_refs)
        ):
            raise ValueError(
                "AnalyzerFindingReceipt evidence references MUST be bounded and unique"
            )
        if self.cause_claim_supported or self.execution_authority:
            raise ValueError("AnalyzerFindingReceipt MUST remain no-cause and read-only")

    def to_dict(self) -> dict[str, object]:
        """Return the stable read-projection representation."""

        evidence_state = self.evidence_state or (
            AnalyzerEvidenceState.COMPLETE
            if self.evidence_complete
            else AnalyzerEvidenceState.INCOMPLETE
        )
        return {
            "schema_version": "1.0.0",
            "idempotency_key": self.idempotency_key,
            "resource_ref": self.resource_ref,
            "resource_kind": self.resource_kind,
            "signal": self.signal,
            "occurred_at": self.occurred_at.isoformat(),
            "recorded_at": (self.recorded_at or self.occurred_at).isoformat(),
            "current_state": self.current_state,
            "detection_latency_seconds": self.detection_latency_seconds,
            "evidence_complete": self.evidence_complete,
            "evidence_state": evidence_state.value,
            "publication": self.publication.value,
            "recovery_closed": self.recovery_closed,
            "recovery_status": self.recovery_status,
            "evidence_refs": list(self.evidence_refs),
            "assessed_by": self.assessed_by,
            "evidence_gaps": list(self.evidence_gaps),
            "cause_claim_supported": self.cause_claim_supported,
            "execution_authority": self.execution_authority,
        }


__all__ = [
    "AnalyzerEvidenceState",
    "AnalyzerFindingReceipt",
    "AnalyzerPublicationStatus",
]
