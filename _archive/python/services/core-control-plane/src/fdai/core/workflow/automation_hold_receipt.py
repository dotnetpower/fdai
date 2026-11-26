"""Canonical automation-hold release receipt and its exact stored-record decoder."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest


@dataclass(frozen=True, slots=True)
class AutomationHoldReleaseReceipt:
    """Content-addressed hold release result with no execution authority."""

    action_id: str
    target_digest: str
    process_id: str
    released_hold_revision: int
    fencing_generation: int
    recovery_admission_digest: str
    recovery_evidence_digest: str
    compensation_receipt_digests: tuple[str, ...]
    source_revision: str
    released_at: datetime
    receipt_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("automation hold release receipt MUST NOT grant execution authority")
        expected = content_digest(
            {
                **asdict(self),
                "released_at": self.released_at.astimezone(UTC).isoformat(),
                "receipt_digest": None,
            }
        )
        if self.receipt_digest != expected:
            raise ValueError("automation hold release receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        action_id: str,
        target_digest: str,
        process_id: str,
        released_hold_revision: int,
        fencing_generation: int,
        recovery_admission_digest: str,
        recovery_evidence_digest: str,
        compensation_receipt_digests: tuple[str, ...],
        source_revision: str,
        released_at: datetime,
    ) -> AutomationHoldReleaseReceipt:
        """Create one canonical receipt from an atomically committed release."""

        normalized_released_at = released_at.astimezone(UTC)
        digest = content_digest(
            {
                "action_id": action_id,
                "target_digest": target_digest,
                "process_id": process_id,
                "released_hold_revision": released_hold_revision,
                "fencing_generation": fencing_generation,
                "recovery_admission_digest": recovery_admission_digest,
                "recovery_evidence_digest": recovery_evidence_digest,
                "compensation_receipt_digests": compensation_receipt_digests,
                "source_revision": source_revision,
                "released_at": normalized_released_at.isoformat(),
                "execution_authority": False,
                "receipt_digest": None,
            }
        )
        return cls(
            action_id=action_id,
            target_digest=target_digest,
            process_id=process_id,
            released_hold_revision=released_hold_revision,
            fencing_generation=fencing_generation,
            recovery_admission_digest=recovery_admission_digest,
            recovery_evidence_digest=recovery_evidence_digest,
            compensation_receipt_digests=compensation_receipt_digests,
            source_revision=source_revision,
            released_at=normalized_released_at,
            receipt_digest=digest,
            execution_authority=False,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical state and audit representation."""

        return {
            **asdict(self),
            "released_at": self.released_at.isoformat(),
        }


def _matching_release_receipt(
    record: object,
    *,
    action_id: str,
    process_id: str,
    hold_revision: int,
    recovery_admission_digest: str,
) -> AutomationHoldReleaseReceipt | None:
    if not isinstance(record, Mapping) or record.get("state") != "released":
        return None
    raw = record.get("release_receipt")
    if not isinstance(raw, Mapping):
        return None
    if (
        raw.get("action_id") != action_id
        or raw.get("process_id") != process_id
        or raw.get("released_hold_revision") != hold_revision
        or raw.get("recovery_admission_digest") != recovery_admission_digest
        or raw.get("execution_authority") is not False
    ):
        return None
    try:
        raw_receipts = raw["compensation_receipt_digests"]
        if not isinstance(raw_receipts, list | tuple) or not all(
            isinstance(item, str) for item in raw_receipts
        ):
            return None
        return AutomationHoldReleaseReceipt(
            action_id=str(raw["action_id"]),
            target_digest=str(raw["target_digest"]),
            process_id=str(raw["process_id"]),
            released_hold_revision=int(raw["released_hold_revision"]),
            fencing_generation=int(raw["fencing_generation"]),
            recovery_admission_digest=str(raw["recovery_admission_digest"]),
            recovery_evidence_digest=str(raw["recovery_evidence_digest"]),
            compensation_receipt_digests=tuple(raw_receipts),
            source_revision=str(raw["source_revision"]),
            released_at=datetime.fromisoformat(str(raw["released_at"])),
            receipt_digest=str(raw["receipt_digest"]),
            execution_authority=False,
        )
    except (KeyError, TypeError, ValueError):
        return None


__all__ = ["AutomationHoldReleaseReceipt"]
