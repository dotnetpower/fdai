"""Stable operation identity comparison for idempotency reservations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .idempotency_reservation import IdempotencyReservationIdentity


def same_operation(
    left: IdempotencyReservationIdentity,
    right: IdempotencyReservationIdentity,
) -> bool:
    """Return whether two attempts identify the same stable operation."""

    return bool(
        left.idempotency_key == right.idempotency_key
        and left.action_digest == right.action_digest
        and left.execution_path is right.execution_path
        and left.execution_fingerprint == right.execution_fingerprint
        and left.source_revision == right.source_revision
        and left.acquisition_receipt.lock_key == right.acquisition_receipt.lock_key
        and left.acquisition_receipt.target_digest == right.acquisition_receipt.target_digest
    )


__all__ = ["same_operation"]
