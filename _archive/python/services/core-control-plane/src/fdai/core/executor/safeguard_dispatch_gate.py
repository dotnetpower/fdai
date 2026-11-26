"""Pre-I/O dispatch gate for persisted safeguard and target-fence evidence."""

from __future__ import annotations

from datetime import datetime

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationTransitionReceipt,
    ReservationState,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchTransitionReceipt,
)
from fdai.core.executor.safeguard_dispatch_support import utc
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
)


def validate_dispatch_start(
    *,
    bundle_persistence_receipt: SafeguardDispatchTransitionReceipt,
    in_flight_reservation_receipt: IdempotencyReservationTransitionReceipt,
    prepared_fence: TargetDispatchFenceRecord,
    in_flight_fence: TargetDispatchFenceRecord,
    started_at: datetime,
) -> None:
    """Fail closed before sink I/O unless exact persisted evidence is current."""

    if (
        type(bundle_persistence_receipt) is not SafeguardDispatchTransitionReceipt
        or bundle_persistence_receipt.prior_record is not None
        or bundle_persistence_receipt.record.state
        is not SafeguardDispatchEvidenceState.BUNDLE_PERSISTED
    ):
        raise ValueError("dispatch start requires authoritative persisted safeguard bundle")
    bundle_record = bundle_persistence_receipt.record
    identity = bundle_record.identity
    normalized_at = utc(started_at, "started_at")
    if (
        type(in_flight_reservation_receipt) is not IdempotencyReservationTransitionReceipt
        or in_flight_reservation_receipt.prior_record is None
        or in_flight_reservation_receipt.prior_record.state is not ReservationState.RESERVED
        or in_flight_reservation_receipt.prior_record.record_digest
        != identity.reservation_record_digest
        or in_flight_reservation_receipt.prior_record.revision != identity.reservation_revision
        or in_flight_reservation_receipt.record.state is not ReservationState.IN_FLIGHT
        or in_flight_reservation_receipt.record.identity.identity_digest
        != identity.reservation_identity_digest
        or in_flight_reservation_receipt.record.identity.acquisition_receipt.attempt
        != identity.reservation_attempt
        or in_flight_reservation_receipt.record.dispatch_started_at is None
        or in_flight_reservation_receipt.recorded_at > normalized_at
        or in_flight_reservation_receipt.record.dispatch_started_at > normalized_at
        or normalized_at >= in_flight_reservation_receipt.record.lease_expires_at
    ):
        raise ValueError("dispatch start requires current in-flight reservation")
    if (
        type(prepared_fence) is not TargetDispatchFenceRecord
        or prepared_fence.state is not TargetDispatchFenceState.PREPARED
        or prepared_fence.identity.identity_digest != identity.target_fence_identity_digest
        or prepared_fence.prior_record_digest != identity.target_fence_record_digest
        or prepared_fence.revision != identity.target_fence_revision + 1
        or prepared_fence.audit_append_receipt_digest != identity.audit_append_receipt_digest
        or prepared_fence.safeguard_bundle_digest != identity.safeguard_bundle_digest
        or prepared_fence.state_changed_at < bundle_persistence_receipt.recorded_at
    ):
        raise ValueError("dispatch start requires exact prepared fence")
    if (
        type(in_flight_fence) is not TargetDispatchFenceRecord
        or in_flight_fence.state is not TargetDispatchFenceState.IN_FLIGHT
        or in_flight_fence.identity != prepared_fence.identity
        or in_flight_fence.prior_record_digest != prepared_fence.record_digest
        or in_flight_fence.revision != prepared_fence.revision + 1
        or in_flight_fence.audit_append_receipt_digest != prepared_fence.audit_append_receipt_digest
        or in_flight_fence.safeguard_bundle_digest != prepared_fence.safeguard_bundle_digest
        or in_flight_fence.audit_append_receipt_digest != identity.audit_append_receipt_digest
        or in_flight_fence.safeguard_bundle_digest != identity.safeguard_bundle_digest
        or in_flight_fence.state_changed_at < prepared_fence.state_changed_at
        or normalized_at < in_flight_fence.state_changed_at
        or normalized_at >= identity.reservation_lease_expires_at
        or normalized_at >= identity.lock_assessment_valid_until
    ):
        raise ValueError("dispatch start requires exact current in-flight fence")


__all__ = ["validate_dispatch_start"]
