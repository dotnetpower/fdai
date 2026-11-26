"""Safeguard dispatch evidence model tamper-resistance tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest
from fdai.core.executor import safeguard_dispatch_checkpoint as dispatch_model
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    ContinuityUnprovenReason,
    DispatchTransportState,
    PreReleaseOwnershipCheckpoint,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
    SafeguardDispatchObservation,
    record_dispatch_observation,
    record_pre_release_checkpoint,
)
from fdai.core.executor.safeguard_dispatch_transition import (
    validate_dispatch_evidence_transition,
    validate_pre_release_assessment,
)

from tests.core.executor.test_safeguard_dispatch_checkpoint import (
    _DIGEST,
    _NOW,
    _assessment,
    _bundle_record,
    _dispatch_started_record,
    _evidence_fixture,
    _observation,
)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": "2.0.0"}, "unsupported"),
        ({"execution_authority": True}, "MUST NOT grant authority"),
        ({"effect_verified": True}, "MUST NOT grant authority"),
        ({"bundle_record_revision": 0}, "bundle record revision MUST be positive"),
        ({"dispatch_start_record_revision": 0}, "record revision MUST be positive"),
        ({"target_fence_revision": 0}, "fence revision MUST be positive"),
        ({"transport_state": "acknowledged"}, "transport state is invalid"),
        ({"sink_state": "accepted"}, "sink state is invalid"),
        ({"authoritative_status_digest": "invalid"}, "authoritative_status_digest"),
        (
            {
                "sink_state": AuthoritativeSinkState.UNKNOWN,
                "sink_operation_reference_digest": None,
            },
            "unknown sink state",
        ),
        ({"observed_at": _NOW - timedelta(microseconds=1)}, "predates dispatch start"),
        ({"observation_digest": "sha256:" + "0" * 64}, "digest mismatched"),
    ),
)
def test_dispatch_observation_rejects_tampered_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    record = _bundle_record()[0]
    _started, observation = _observation(record)

    with pytest.raises(ValueError, match=message):
        replace(observation, **cast(Any, changes))


def test_dispatch_observation_factory_rejects_subclass_and_missing_start() -> None:
    record = _bundle_record()[0]

    class DerivedObservation(SafeguardDispatchObservation):
        pass

    with pytest.raises(TypeError, match="does not support subclasses"):
        DerivedObservation.create(
            dispatch_start_record=record,
            transport_state=DispatchTransportState.UNKNOWN,
            sink_state=AuthoritativeSinkState.UNKNOWN,
            sink_operation_reference_digest=None,
            authoritative_status_digest=None,
            observed_at=_NOW,
        )
    with pytest.raises(ValueError, match="requires durable dispatch start"):
        SafeguardDispatchObservation.create(
            dispatch_start_record=record,
            transport_state=DispatchTransportState.UNKNOWN,
            sink_state=AuthoritativeSinkState.UNKNOWN,
            sink_operation_reference_digest=None,
            authoritative_status_digest=None,
            observed_at=_NOW,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": "2.0.0"}, "unsupported"),
        ({"execution_authority": True}, "MUST NOT grant authority"),
        ({"effect_verified": True}, "MUST NOT grant authority"),
        ({"continuity_state": "current"}, "continuity state is invalid"),
        ({"assessment_digest": "invalid"}, "assessment_digest"),
        ({"verifier_id": ""}, "verifier_id"),
        ({"evaluated_at": _NOW.replace(tzinfo=None)}, "evaluated_at"),
        ({"rejection_reasons": []}, "rejection reasons MUST be canonical"),
        (
            {"rejection_reasons": ("lock_lost", "lock_lost")},
            "rejection reasons MUST be canonical",
        ),
        ({"unproven_reason": "stale"}, "continuity reason is invalid"),
        ({"checkpoint_digest": "sha256:" + "0" * 64}, "digest mismatched"),
    ),
)
def test_pre_release_checkpoint_rejects_tampered_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    record, reservation = _bundle_record()
    assessment = _assessment(reservation)
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=assessment,
        not_before=_NOW,
        observed_at=assessment.evaluated_at,
    )

    with pytest.raises(ValueError, match=message):
        replace(checkpoint, **cast(Any, changes))


def test_pre_release_checkpoint_factories_reject_invalid_inputs() -> None:
    record, reservation = _bundle_record()
    assessment = _assessment(reservation)

    class DerivedCheckpoint(PreReleaseOwnershipCheckpoint):
        pass

    with pytest.raises(TypeError, match="does not support subclasses"):
        DerivedCheckpoint.from_assessment(
            evidence_identity=record.identity,
            assessment=assessment,
            not_before=_NOW,
            observed_at=assessment.evaluated_at,
        )
    with pytest.raises(ValueError, match="requires exact identity"):
        PreReleaseOwnershipCheckpoint.from_assessment(
            evidence_identity=cast(Any, object()),
            assessment=assessment,
            not_before=_NOW,
            observed_at=assessment.evaluated_at,
        )
    with pytest.raises(ValueError, match="requires exact assessment"):
        PreReleaseOwnershipCheckpoint.from_assessment(
            evidence_identity=record.identity,
            assessment=cast(Any, object()),
            not_before=_NOW,
            observed_at=assessment.evaluated_at,
        )
    with pytest.raises(ValueError, match="continuity reason is invalid"):
        PreReleaseOwnershipCheckpoint.unproven(
            evidence_identity=record.identity,
            reason=cast(Any, "stale"),
            observed_at=_NOW,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": "2.0.0"}, "unsupported"),
        ({"execution_authority": True}, "MUST NOT grant authority"),
        ({"effect_verified": True}, "MUST NOT grant authority"),
        ({"identity": object()}, "requires exact identity"),
        ({"bundle": object()}, "requires exact bundle"),
        ({"state": "bundle_persisted"}, "state is invalid"),
        ({"revision": 0}, "revision MUST be positive"),
        ({"prior_record_digest": _DIGEST}, "has predecessor"),
        ({"dispatch_start_checkpoint": object()}, "checkpoint is invalid"),
        ({"dispatch_observation": object()}, "observation is invalid"),
        ({"pre_release_checkpoint": object()}, "checkpoint is invalid"),
        ({"independent_effect_state": "verified"}, "MUST start pending"),
        ({"state_changed_at": _NOW.replace(tzinfo=None)}, "state_changed_at"),
        ({"record_digest": "sha256:" + "0" * 64}, "digest mismatched"),
    ),
)
def test_safeguard_dispatch_record_rejects_tampered_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    record = _bundle_record()[0]

    with pytest.raises(ValueError, match=message):
        replace(record, **cast(Any, changes))


def test_safeguard_dispatch_record_rejects_missing_transition_predecessor() -> None:
    record = _bundle_record()[0]
    started, _receipt = _dispatch_started_record(record)

    with pytest.raises(ValueError, match="transition lacks predecessor"):
        replace(started, prior_record_digest=None)


def test_safeguard_dispatch_record_factory_rejects_subclasses() -> None:
    record, _reservation, preparing, _prepared, context = _evidence_fixture()

    class DerivedRecord(SafeguardDispatchEvidenceRecord):
        pass

    with pytest.raises(TypeError, match="does not support subclasses"):
        DerivedRecord.create_bundle_persisted(
            preparing_fence=preparing,
            persistence_context=context,
            bundle=record.bundle,
            persisted_at=_NOW,
        )


def test_current_checkpoint_shape_rejects_rejection_reason() -> None:
    record, reservation = _bundle_record()
    assessment = _assessment(reservation)
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=assessment,
        not_before=_NOW,
        observed_at=assessment.evaluated_at,
    )

    with pytest.raises(ValueError, match="current pre-release checkpoint shape is invalid"):
        replace(
            checkpoint,
            rejection_reasons=(ContinuityUnprovenReason.INELIGIBLE.value,),
        )


def test_transition_validator_rejects_assessment_on_pre_release_only_edges() -> None:
    record, reservation = _bundle_record()
    started, observation = _observation(record)
    assessment = _assessment(reservation)
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )

    with pytest.raises(ValueError, match="dispatch-start edge cannot carry"):
        validate_dispatch_evidence_transition(
            record,
            started,
            current_lock_assessment=assessment,
        )
    with pytest.raises(ValueError, match="dispatch-observation edge cannot carry"):
        validate_dispatch_evidence_transition(
            started,
            observed,
            current_lock_assessment=assessment,
        )
    invalid_edge = dispatch_model._build_record(  # noqa: SLF001
        identity=record.identity,
        bundle=record.bundle,
        state=SafeguardDispatchEvidenceState.DISPATCH_STARTED,
        revision=observed.revision + 1,
        prior_record_digest=observed.record_digest,
        dispatch_start_checkpoint=started.dispatch_start_checkpoint,
        state_changed_at=observed.state_changed_at,
    )
    with pytest.raises(ValueError, match="transition edge is invalid"):
        validate_dispatch_evidence_transition(observed, invalid_edge)


def test_pre_release_assessment_and_unproven_edges_fail_closed() -> None:
    record, reservation = _bundle_record()
    started, observation = _observation(record)
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    assessment = _assessment(reservation)
    current_checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=assessment,
        not_before=observation.observed_at,
        observed_at=assessment.evaluated_at,
    )
    current = record_pre_release_checkpoint(
        observed,
        checkpoint=current_checkpoint,
        current_lock_assessment=assessment,
        changed_at=current_checkpoint.observed_at,
    )
    unproven_checkpoint = PreReleaseOwnershipCheckpoint.unproven(
        evidence_identity=record.identity,
        reason=ContinuityUnprovenReason.MISSING,
        observed_at=observation.observed_at,
    )
    unproven = record_pre_release_checkpoint(
        observed,
        checkpoint=unproven_checkpoint,
        changed_at=unproven_checkpoint.observed_at,
    )

    with pytest.raises(ValueError, match="current assessment is not exact"):
        validate_pre_release_assessment(current, None)
    with pytest.raises(ValueError, match="cannot carry current assessment"):
        validate_dispatch_evidence_transition(
            observed,
            unproven,
            current_lock_assessment=assessment,
        )
