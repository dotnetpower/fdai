"""Cross-record validation for the safeguard dispatch evidence lifecycle."""

from __future__ import annotations

from fdai.core.executor.idempotency_reservation import ReservationState
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    PreReleaseContinuityState,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.target_dispatch_fence import TargetDispatchFenceState
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    require_current_lock_ownership,
)


def validate_dispatch_evidence_transition(
    prior: SafeguardDispatchEvidenceRecord,
    current: SafeguardDispatchEvidenceRecord,
    *,
    current_lock_assessment: LiveLockOwnershipAssessment | None = None,
) -> None:
    """Validate exact predecessor, identity, bundle, and legal evidence edge."""

    if (
        current.identity != prior.identity
        or current.bundle != prior.bundle
        or current.revision != prior.revision + 1
        or current.prior_record_digest != prior.record_digest
        or current.state_changed_at < prior.state_changed_at
        or current.independent_effect_state != prior.independent_effect_state
    ):
        raise ValueError("safeguard dispatch evidence predecessor mismatched")
    if (
        prior.state is SafeguardDispatchEvidenceState.BUNDLE_PERSISTED
        and current.state is SafeguardDispatchEvidenceState.DISPATCH_STARTED
    ):
        if current_lock_assessment is not None:
            raise ValueError("dispatch-start edge cannot carry pre-release assessment")
        _validate_dispatch_start_edge(prior, current)
        return
    if (
        prior.state is SafeguardDispatchEvidenceState.DISPATCH_STARTED
        and current.state is SafeguardDispatchEvidenceState.DISPATCH_OBSERVED
    ):
        if current_lock_assessment is not None:
            raise ValueError("dispatch-observation edge cannot carry pre-release assessment")
        _validate_dispatch_observation_edge(prior, current)
        return
    if (
        prior.state is SafeguardDispatchEvidenceState.DISPATCH_OBSERVED
        and current.state is SafeguardDispatchEvidenceState.PRE_RELEASE
        and current.dispatch_start_checkpoint == prior.dispatch_start_checkpoint
        and current.dispatch_observation == prior.dispatch_observation
    ):
        _validate_pre_release_edge(
            current,
            current_lock_assessment=current_lock_assessment,
        )
        return
    raise ValueError("safeguard dispatch evidence transition edge is invalid")


def validate_pre_release_assessment(
    record: SafeguardDispatchEvidenceRecord,
    assessment: LiveLockOwnershipAssessment | None,
) -> None:
    """Bind a current checkpoint to its full provider-attested assessment."""

    checkpoint = record.pre_release_checkpoint
    observation = record.dispatch_observation
    if (
        record.state is not SafeguardDispatchEvidenceState.PRE_RELEASE
        or checkpoint is None
        or observation is None
        or checkpoint.continuity_state is not PreReleaseContinuityState.CURRENT
        or type(assessment) is not LiveLockOwnershipAssessment
        or assessment.assessment_digest != checkpoint.assessment_digest
        or assessment.acquisition_receipt.receipt_digest
        != record.identity.acquisition_receipt_digest
        or assessment.verifier_id != record.identity.lock_verifier_id
        or assessment.verifier_version != record.identity.lock_verifier_version
        or assessment.trust_anchor_id != record.identity.lock_trust_anchor_id
        or assessment.evaluated_at < observation.observed_at
        or assessment.evaluated_at != checkpoint.evaluated_at
        or assessment.valid_until != checkpoint.valid_until
        or record.state_changed_at >= assessment.valid_until
    ):
        raise ValueError("pre-release current assessment is not exact")
    require_current_lock_ownership(
        assessment,
        observed_at=record.state_changed_at,
    )


def _validate_dispatch_observation_edge(
    prior: SafeguardDispatchEvidenceRecord,
    current: SafeguardDispatchEvidenceRecord,
) -> None:
    start = prior.dispatch_start_checkpoint
    observation = current.dispatch_observation
    if (
        start is None
        or observation is None
        or current.dispatch_start_checkpoint != start
        or current.pre_release_checkpoint is not None
        or observation.bundle_record_digest != start.bundle_record_digest
        or observation.bundle_record_revision != start.bundle_record_revision
        or observation.dispatch_start_record_digest != prior.record_digest
        or observation.dispatch_start_record_revision != prior.revision
        or observation.in_flight_reservation_receipt_digest
        != start.in_flight_reservation_receipt.receipt_digest
        or observation.target_fence_record_digest != start.in_flight_fence.record_digest
        or observation.target_fence_revision != start.in_flight_fence.revision
        or observation.dispatch_started_at != start.dispatch_started_at
        or current.state_changed_at < observation.observed_at
    ):
        raise ValueError("dispatch observation edge is invalid")


def _validate_pre_release_edge(
    current: SafeguardDispatchEvidenceRecord,
    *,
    current_lock_assessment: LiveLockOwnershipAssessment | None,
) -> None:
    checkpoint = current.pre_release_checkpoint
    observation = current.dispatch_observation
    if (
        checkpoint is None
        or observation is None
        or checkpoint.evidence_identity_digest != current.identity.identity_digest
        or checkpoint.acquisition_receipt_digest != current.identity.acquisition_receipt_digest
        or checkpoint.observed_at < observation.observed_at
        or current.state_changed_at < checkpoint.observed_at
    ):
        raise ValueError("pre-release checkpoint edge is invalid")
    if checkpoint.continuity_state is PreReleaseContinuityState.CURRENT:
        if (
            checkpoint.assessment_digest is None
            or checkpoint.verifier_id != current.identity.lock_verifier_id
            or checkpoint.verifier_version != current.identity.lock_verifier_version
            or checkpoint.trust_anchor_id != current.identity.lock_trust_anchor_id
            or checkpoint.evaluated_at is None
            or checkpoint.evaluated_at < observation.observed_at
            or checkpoint.valid_until is None
            or current.state_changed_at >= checkpoint.valid_until
        ):
            raise ValueError("pre-release current ownership edge is invalid")
        validate_pre_release_assessment(
            current,
            current_lock_assessment,
        )
    elif current_lock_assessment is not None:
        raise ValueError("continuity-unproven edge cannot carry current assessment")


def _validate_dispatch_start_edge(
    prior: SafeguardDispatchEvidenceRecord,
    current: SafeguardDispatchEvidenceRecord,
) -> None:
    start = current.dispatch_start_checkpoint
    if (
        start is None
        or current.dispatch_observation is not None
        or current.pre_release_checkpoint is not None
        or start.evidence_identity_digest != prior.identity.identity_digest
        or start.bundle_record_digest != prior.record_digest
        or start.bundle_record_revision != prior.revision
        or current.state_changed_at < start.dispatch_started_at
    ):
        raise ValueError("dispatch-start evidence edge is invalid")
    identity = prior.identity
    reservation = start.in_flight_reservation_receipt
    if (
        reservation.prior_record is None
        or reservation.prior_record.state is not ReservationState.RESERVED
        or reservation.prior_record.record_digest != identity.reservation_record_digest
        or reservation.prior_record.revision != identity.reservation_revision
        or reservation.record.state is not ReservationState.IN_FLIGHT
        or reservation.record.identity.identity_digest != identity.reservation_identity_digest
        or reservation.record.identity.acquisition_receipt.attempt != identity.reservation_attempt
        or reservation.record.dispatch_started_at is None
        or reservation.recorded_at > start.dispatch_started_at
        or reservation.record.dispatch_started_at > start.dispatch_started_at
        or start.dispatch_started_at >= reservation.record.lease_expires_at
    ):
        raise ValueError("dispatch-start reservation lineage is invalid")
    prepared = start.prepared_fence
    in_flight = start.in_flight_fence
    if (
        prepared.state is not TargetDispatchFenceState.PREPARED
        or prepared.identity.identity_digest != identity.target_fence_identity_digest
        or prepared.prior_record_digest != identity.target_fence_record_digest
        or prepared.revision != identity.target_fence_revision + 1
        or prepared.audit_append_receipt_digest != identity.audit_append_receipt_digest
        or prepared.safeguard_bundle_digest != identity.safeguard_bundle_digest
        or in_flight.state is not TargetDispatchFenceState.IN_FLIGHT
        or in_flight.identity != prepared.identity
        or in_flight.prior_record_digest != prepared.record_digest
        or in_flight.revision != prepared.revision + 1
        or in_flight.audit_append_receipt_digest != prepared.audit_append_receipt_digest
        or in_flight.safeguard_bundle_digest != prepared.safeguard_bundle_digest
        or in_flight.state_changed_at < prepared.state_changed_at
        or start.dispatch_started_at < in_flight.state_changed_at
        or start.dispatch_started_at >= identity.reservation_lease_expires_at
        or start.dispatch_started_at >= identity.lock_assessment_valid_until
    ):
        raise ValueError("dispatch-start target fence lineage is invalid")


__all__ = [
    "validate_dispatch_evidence_transition",
    "validate_pre_release_assessment",
]
