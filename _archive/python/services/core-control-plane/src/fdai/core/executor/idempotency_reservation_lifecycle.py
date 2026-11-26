"""Monotonic state transitions for executor idempotency reservations."""

from __future__ import annotations

from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from .idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    ReservationEvidenceKind,
    ReservationState,
    _build_record,
    _utc,
    _validate_digest,
)
from .idempotency_reservation_identity import same_operation


def dispatch_permitted(
    record: IdempotencyReservationRecord,
    *,
    at: datetime,
) -> bool:
    """Allow only the first current reservation to begin dispatch."""

    observed_at = _utc(at, "dispatch_at")
    return bool(
        record.state is ReservationState.RESERVED
        and record.reserved_at <= observed_at < record.lease_expires_at
    )


def begin_dispatch(
    record: IdempotencyReservationRecord,
    *,
    at: datetime,
) -> IdempotencyReservationRecord:
    """Move a current reservation to in-flight before calling the sink."""

    started_at = _utc(at, "dispatch_started_at")
    if not dispatch_permitted(record, at=started_at):
        raise ValueError("idempotency reservation is not eligible to dispatch")
    return _build_record(
        identity=record.identity,
        state=ReservationState.IN_FLIGHT,
        revision=record.revision + 1,
        reserved_at=record.reserved_at,
        lease_expires_at=record.lease_expires_at,
        state_changed_at=started_at,
        dispatch_started_at=started_at,
    )


def expire_reservation(
    record: IdempotencyReservationRecord,
    *,
    at: datetime,
    dispatch_never_began_digest: str | None = None,
) -> IdempotencyReservationRecord:
    """Expire without converting an ambiguous in-flight effect into retry."""

    expired_at = _utc(at, "expired_at")
    if expired_at < record.lease_expires_at:
        raise ValueError("idempotency reservation lease has not expired")
    if record.state is ReservationState.RESERVED:
        if dispatch_never_began_digest is None:
            raise ValueError("abandonment requires proof that dispatch never began")
        _validate_digest("dispatch_never_began_digest", dispatch_never_began_digest)
        return _build_record(
            identity=record.identity,
            state=ReservationState.ABANDONED,
            revision=record.revision + 1,
            reserved_at=record.reserved_at,
            lease_expires_at=record.lease_expires_at,
            state_changed_at=expired_at,
            evidence_kind=ReservationEvidenceKind.DISPATCH_NEVER_BEGAN,
            evidence_digest=dispatch_never_began_digest,
        )
    if record.state is ReservationState.IN_FLIGHT:
        return _build_record(
            identity=record.identity,
            state=ReservationState.OUTCOME_UNKNOWN,
            revision=record.revision + 1,
            reserved_at=record.reserved_at,
            lease_expires_at=record.lease_expires_at,
            state_changed_at=expired_at,
            dispatch_started_at=record.dispatch_started_at,
            evidence_kind=ReservationEvidenceKind.LEASE_EXPIRED,
            evidence_digest=content_digest(
                {
                    "domain": "idempotency-reservation-expiry",
                    "record_digest": record.record_digest,
                    "expired_at": expired_at.isoformat(),
                }
            ),
        )
    raise ValueError("idempotency reservation state cannot be expired")


def abandon_reservation_before_dispatch(
    record: IdempotencyReservationRecord,
    *,
    at: datetime,
    dispatch_never_began_digest: str,
) -> IdempotencyReservationRecord:
    """Close a reserved attempt from durable proof that provider dispatch never began."""

    abandoned_at = _utc(at, "abandoned_at")
    if record.state is not ReservationState.RESERVED:
        raise ValueError("only a reserved idempotency state can be abandoned before dispatch")
    if abandoned_at < record.state_changed_at:
        raise ValueError("idempotency abandonment predates reservation")
    _validate_digest("dispatch_never_began_digest", dispatch_never_began_digest)
    return _build_record(
        identity=record.identity,
        state=ReservationState.ABANDONED,
        revision=record.revision + 1,
        reserved_at=record.reserved_at,
        lease_expires_at=record.lease_expires_at,
        state_changed_at=abandoned_at,
        evidence_kind=ReservationEvidenceKind.DISPATCH_NEVER_BEGAN,
        evidence_digest=dispatch_never_began_digest,
    )


def complete_reservation(
    record: IdempotencyReservationRecord,
    *,
    at: datetime,
    terminal_outcome_digest: str,
    authoritative_status_digest: str,
    irrevocable_non_acceptance: bool = False,
) -> IdempotencyReservationRecord:
    """Resolve an in-flight or unknown reservation to one terminal outcome."""

    completed_at = _utc(at, "completed_at")
    if record.state not in {ReservationState.IN_FLIGHT, ReservationState.OUTCOME_UNKNOWN}:
        raise ValueError("idempotency reservation is not awaiting a terminal outcome")
    if (
        record.dispatch_started_at is None
        or completed_at < record.dispatch_started_at
        or completed_at < record.state_changed_at
    ):
        raise ValueError("idempotency terminal outcome predates current state")
    _validate_digest("terminal_outcome_digest", terminal_outcome_digest)
    _validate_digest("authoritative_status_digest", authoritative_status_digest)
    evidence_kind = (
        ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE
        if irrevocable_non_acceptance
        else ReservationEvidenceKind.SINK_TERMINAL_OUTCOME
    )
    return _build_record(
        identity=record.identity,
        state=ReservationState.TERMINAL,
        revision=record.revision + 1,
        reserved_at=record.reserved_at,
        lease_expires_at=record.lease_expires_at,
        state_changed_at=completed_at,
        dispatch_started_at=record.dispatch_started_at,
        evidence_kind=evidence_kind,
        evidence_digest=authoritative_status_digest,
        terminal_outcome_digest=terminal_outcome_digest,
    )


def complete_reservation_from_verifier(
    record: IdempotencyReservationRecord,
    *,
    at: datetime,
    terminal_outcome_digest: str,
    independent_effect_receipt_digest: str,
) -> IdempotencyReservationRecord:
    """Resolve an in-flight or unknown reservation from independent evidence."""

    completed_at = _utc(at, "completed_at")
    if record.state not in {ReservationState.IN_FLIGHT, ReservationState.OUTCOME_UNKNOWN}:
        raise ValueError("idempotency reservation is not awaiting a terminal outcome")
    if (
        record.dispatch_started_at is None
        or completed_at < record.dispatch_started_at
        or completed_at < record.state_changed_at
    ):
        raise ValueError("idempotency terminal outcome predates current state")
    _validate_digest("terminal_outcome_digest", terminal_outcome_digest)
    _validate_digest(
        "independent_effect_receipt_digest",
        independent_effect_receipt_digest,
    )
    return _build_record(
        identity=record.identity,
        state=ReservationState.TERMINAL,
        revision=record.revision + 1,
        reserved_at=record.reserved_at,
        lease_expires_at=record.lease_expires_at,
        state_changed_at=completed_at,
        dispatch_started_at=record.dispatch_started_at,
        evidence_kind=ReservationEvidenceKind.INDEPENDENT_EFFECT_OUTCOME,
        evidence_digest=independent_effect_receipt_digest,
        terminal_outcome_digest=terminal_outcome_digest,
    )


def quarantine_reservation(
    record: IdempotencyReservationRecord,
    *,
    at: datetime,
    continuity_evidence_digest: str,
) -> IdempotencyReservationRecord:
    """Move an in-flight reservation to durable unknown-outcome quarantine."""

    quarantined_at = _utc(at, "quarantined_at")
    if record.state is not ReservationState.IN_FLIGHT:
        raise ValueError("only an in-flight reservation can enter continuity quarantine")
    if record.dispatch_started_at is None or quarantined_at < record.dispatch_started_at:
        raise ValueError("idempotency quarantine predates dispatch")
    _validate_digest("continuity_evidence_digest", continuity_evidence_digest)
    return _build_record(
        identity=record.identity,
        state=ReservationState.OUTCOME_UNKNOWN,
        revision=record.revision + 1,
        reserved_at=record.reserved_at,
        lease_expires_at=record.lease_expires_at,
        state_changed_at=quarantined_at,
        dispatch_started_at=record.dispatch_started_at,
        evidence_kind=ReservationEvidenceKind.CONTINUITY_UNPROVEN,
        evidence_digest=continuity_evidence_digest,
    )


def reopen_reservation(
    record: IdempotencyReservationRecord,
    *,
    candidate_identity: IdempotencyReservationIdentity,
    reserved_at: datetime,
    lease_expires_at: datetime,
) -> IdempotencyReservationRecord:
    """Create a new attempt only after authoritative non-dispatch evidence."""

    recoverable = bool(
        record.state is ReservationState.ABANDONED
        or (
            record.state is ReservationState.TERMINAL
            and record.evidence_kind is ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE
        )
    )
    if not recoverable:
        raise ValueError("idempotency reservation has no safe recovery evidence")
    if not same_operation(record.identity, candidate_identity):
        raise ValueError("idempotency reservation recovery changes the stable operation")
    if (
        candidate_identity.acquisition_receipt.attempt
        <= record.identity.acquisition_receipt.attempt
    ):
        raise ValueError("idempotency reservation recovery attempt MUST increase")
    normalized_reserved_at = _utc(reserved_at, "reserved_at")
    if normalized_reserved_at < record.state_changed_at:
        raise ValueError("idempotency reservation recovery predates its predecessor")
    if (
        candidate_identity.acquisition_receipt.acquired_at < record.state_changed_at
        or candidate_identity.acquisition_receipt.acquired_at > normalized_reserved_at
    ):
        raise ValueError("idempotency reservation recovery acquisition time is invalid")
    return _build_record(
        identity=candidate_identity,
        state=ReservationState.RESERVED,
        revision=record.revision + 1,
        reserved_at=normalized_reserved_at,
        lease_expires_at=_utc(lease_expires_at, "lease_expires_at"),
        state_changed_at=normalized_reserved_at,
    )


__all__ = [
    "abandon_reservation_before_dispatch",
    "begin_dispatch",
    "complete_reservation",
    "complete_reservation_from_verifier",
    "dispatch_permitted",
    "expire_reservation",
    "quarantine_reservation",
    "reopen_reservation",
]
