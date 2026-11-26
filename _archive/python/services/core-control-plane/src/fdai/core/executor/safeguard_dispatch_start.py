"""Durable pre-I/O dispatch-start checkpoint."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Self

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationTransitionReceipt,
)
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest,
    validate_digest,
    validate_utc,
)
from fdai.core.executor.target_dispatch_fence import TargetDispatchFenceRecord

if TYPE_CHECKING:
    from fdai.core.executor.safeguard_dispatch_store import (
        SafeguardDispatchTransitionReceipt,
    )


@dataclass(frozen=True, slots=True)
class SafeguardDispatchStartCheckpoint:
    """Exact durable lineage that must exist before transport I/O begins."""

    schema_version: Literal["1.0.0"]
    evidence_identity_digest: str
    bundle_record_digest: str
    bundle_record_revision: int
    bundle_persistence_receipt_digest: str
    in_flight_reservation_receipt: IdempotencyReservationTransitionReceipt
    prepared_fence: TargetDispatchFenceRecord
    in_flight_fence: TargetDispatchFenceRecord
    dispatch_started_at: datetime
    checkpoint_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported safeguard dispatch-start checkpoint schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("safeguard dispatch-start checkpoint MUST NOT grant authority")
        for name, value in (
            ("evidence_identity_digest", self.evidence_identity_digest),
            ("bundle_record_digest", self.bundle_record_digest),
            (
                "bundle_persistence_receipt_digest",
                self.bundle_persistence_receipt_digest,
            ),
        ):
            validate_digest(name, value)
        if type(self.bundle_record_revision) is not int or self.bundle_record_revision < 1:
            raise ValueError("safeguard dispatch-start bundle revision MUST be positive")
        if type(self.in_flight_reservation_receipt) is not IdempotencyReservationTransitionReceipt:
            raise ValueError("safeguard dispatch-start reservation receipt is invalid")
        if type(self.prepared_fence) is not TargetDispatchFenceRecord:
            raise ValueError("safeguard dispatch-start prepared fence is invalid")
        if type(self.in_flight_fence) is not TargetDispatchFenceRecord:
            raise ValueError("safeguard dispatch-start in-flight fence is invalid")
        validate_utc("dispatch_started_at", self.dispatch_started_at)
        validate_digest("checkpoint_digest", self.checkpoint_digest)
        if self.checkpoint_digest != payload_digest(
            asdict(self),
            "safeguard-dispatch-start-checkpoint",
            digest_field="checkpoint_digest",
        ):
            raise ValueError("safeguard dispatch-start checkpoint digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        bundle_persistence_receipt: SafeguardDispatchTransitionReceipt,
        in_flight_reservation_receipt: IdempotencyReservationTransitionReceipt,
        prepared_fence: TargetDispatchFenceRecord,
        in_flight_fence: TargetDispatchFenceRecord,
        dispatch_started_at: datetime,
    ) -> Self:
        """Create a no-authority checkpoint after authoritative bundle readback."""

        if cls is not SafeguardDispatchStartCheckpoint:
            raise TypeError("safeguard dispatch-start checkpoint does not support subclasses")
        from fdai.core.executor.safeguard_dispatch_gate import (
            validate_dispatch_start,
        )
        from fdai.core.executor.safeguard_dispatch_store import (
            SafeguardDispatchTransitionReceipt,
        )

        if (
            type(bundle_persistence_receipt) is not SafeguardDispatchTransitionReceipt
            or bundle_persistence_receipt.prior_record is not None
        ):
            raise ValueError("dispatch start requires authoritative bundle persistence")
        bundle_record = bundle_persistence_receipt.record
        validate_dispatch_start(
            bundle_persistence_receipt=bundle_persistence_receipt,
            in_flight_reservation_receipt=in_flight_reservation_receipt,
            prepared_fence=prepared_fence,
            in_flight_fence=in_flight_fence,
            started_at=dispatch_started_at,
        )
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_identity_digest": bundle_record.identity.identity_digest,
            "bundle_record_digest": bundle_record.record_digest,
            "bundle_record_revision": bundle_record.revision,
            "bundle_persistence_receipt_digest": (bundle_persistence_receipt.receipt_digest),
            "in_flight_reservation_receipt": in_flight_reservation_receipt,
            "prepared_fence": prepared_fence,
            "in_flight_fence": in_flight_fence,
            "dispatch_started_at": dispatch_started_at,
            "execution_authority": False,
            "effect_verified": False,
        }
        values["checkpoint_digest"] = payload_digest(
            values,
            "safeguard-dispatch-start-checkpoint",
            digest_field="checkpoint_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


__all__ = ["SafeguardDispatchStartCheckpoint"]
