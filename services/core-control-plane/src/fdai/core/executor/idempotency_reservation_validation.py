"""State-shape validation for crash-safe idempotency reservations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fdai.core.executor.idempotency_reservation import IdempotencyReservationRecord


def validate_reservation_state_shape(record: IdempotencyReservationRecord) -> None:
    """Reject a reservation whose evidence does not match its lifecycle state."""

    from fdai.core.executor.idempotency_reservation import (
        ReservationEvidenceKind,
        ReservationState,
    )

    if record.state is ReservationState.RESERVED:
        if record.state_changed_at != record.reserved_at:
            raise ValueError("reserved idempotency state change time is invalid")
        if any(
            value is not None
            for value in (
                record.dispatch_started_at,
                record.evidence_kind,
                record.evidence_digest,
                record.terminal_outcome_digest,
            )
        ):
            raise ValueError("reserved idempotency state contains later-phase evidence")
    elif record.state is ReservationState.IN_FLIGHT:
        if (
            record.dispatch_started_at is None
            or record.state_changed_at != record.dispatch_started_at
            or record.dispatch_started_at >= record.lease_expires_at
            or record.evidence_kind is not None
            or record.evidence_digest is not None
            or record.terminal_outcome_digest is not None
        ):
            raise ValueError("in-flight idempotency state shape is invalid")
    elif record.state is ReservationState.ABANDONED:
        if (
            record.dispatch_started_at is not None
            or record.state_changed_at < record.lease_expires_at
            or record.evidence_kind is not ReservationEvidenceKind.DISPATCH_NEVER_BEGAN
            or record.evidence_digest is None
            or record.terminal_outcome_digest is not None
        ):
            raise ValueError("abandoned idempotency state requires no-dispatch evidence")
    elif record.state is ReservationState.OUTCOME_UNKNOWN:
        if (
            record.dispatch_started_at is None
            or record.evidence_kind
            not in {
                ReservationEvidenceKind.LEASE_EXPIRED,
                ReservationEvidenceKind.CONTINUITY_UNPROVEN,
            }
            or record.evidence_digest is None
            or record.terminal_outcome_digest is not None
        ):
            raise ValueError("unknown idempotency state requires continuity evidence")
        if (
            record.evidence_kind is ReservationEvidenceKind.LEASE_EXPIRED
            and record.state_changed_at < record.lease_expires_at
        ):
            raise ValueError("lease-expired idempotency evidence predates expiry")
        if (
            record.evidence_kind is ReservationEvidenceKind.CONTINUITY_UNPROVEN
            and record.state_changed_at < record.dispatch_started_at
        ):
            raise ValueError("continuity evidence predates dispatch")
    elif (
        record.dispatch_started_at is None
        or record.state_changed_at < record.dispatch_started_at
        or record.evidence_kind
        not in {
            ReservationEvidenceKind.SINK_TERMINAL_OUTCOME,
            ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE,
            ReservationEvidenceKind.INDEPENDENT_EFFECT_OUTCOME,
        }
        or record.evidence_digest is None
        or record.terminal_outcome_digest is None
    ):
        raise ValueError("terminal idempotency state requires authoritative sink evidence")


__all__ = ["validate_reservation_state_shape"]
