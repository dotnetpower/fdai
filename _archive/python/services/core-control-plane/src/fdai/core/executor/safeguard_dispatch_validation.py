"""Shape validation for durable safeguard dispatch checkpoints."""

from __future__ import annotations

from fdai.core.executor.safeguard_dispatch_checkpoint import (
    PreReleaseContinuityState,
    PreReleaseOwnershipCheckpoint,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)


def validate_checkpoint_shape(checkpoint: PreReleaseOwnershipCheckpoint) -> None:
    """Require a complete current assessment or a typed unproven reason."""

    assessment_fields = (
        checkpoint.assessment_digest,
        checkpoint.verifier_id,
        checkpoint.verifier_version,
        checkpoint.trust_anchor_id,
        checkpoint.evaluated_at,
        checkpoint.valid_until,
    )
    if checkpoint.continuity_state is PreReleaseContinuityState.CURRENT:
        if (
            any(value is None for value in assessment_fields)
            or checkpoint.rejection_reasons
            or checkpoint.unproven_reason is not None
            or checkpoint.evaluated_at is None
            or checkpoint.valid_until is None
            or not (checkpoint.evaluated_at <= checkpoint.observed_at < checkpoint.valid_until)
        ):
            raise ValueError("current pre-release checkpoint shape is invalid")
    elif checkpoint.unproven_reason is None:
        raise ValueError("continuity-unproven checkpoint requires a reason")


def validate_record_shape(record: SafeguardDispatchEvidenceRecord) -> None:
    """Require the checkpoints that correspond to the record's monotonic state."""

    if record.state is SafeguardDispatchEvidenceState.BUNDLE_PERSISTED:
        if (
            record.revision != 1
            or record.dispatch_start_checkpoint is not None
            or record.dispatch_observation is not None
            or record.pre_release_checkpoint is not None
        ):
            raise ValueError("bundle-persisted dispatch evidence shape is invalid")
    elif record.state is SafeguardDispatchEvidenceState.DISPATCH_STARTED:
        if (
            record.dispatch_start_checkpoint is None
            or record.dispatch_observation is not None
            or record.pre_release_checkpoint is not None
            or record.dispatch_start_checkpoint.evidence_identity_digest
            != record.identity.identity_digest
        ):
            raise ValueError("dispatch-started evidence shape is invalid")
    elif record.state is SafeguardDispatchEvidenceState.DISPATCH_OBSERVED:
        if (
            record.dispatch_start_checkpoint is None
            or record.dispatch_observation is None
            or record.pre_release_checkpoint is not None
            or record.dispatch_observation.evidence_identity_digest
            != record.identity.identity_digest
        ):
            raise ValueError("dispatch-observed evidence shape is invalid")
    elif (
        record.dispatch_start_checkpoint is None
        or record.dispatch_observation is None
        or record.pre_release_checkpoint is None
        or record.pre_release_checkpoint.evidence_identity_digest != record.identity.identity_digest
    ):
        raise ValueError("pre-release dispatch evidence shape is invalid")


__all__ = ["validate_checkpoint_shape", "validate_record_shape"]
