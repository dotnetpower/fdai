"""Crash-safe idempotency reservation contract tests."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import pytest
from fdai.core.executor import idempotency_reservation as reservation_model
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    IdempotencyReservationReserveResult,
    IdempotencyReservationTransitionReceipt,
    ReservationEvidenceKind,
    ReservationMatch,
    ReservationState,
    begin_dispatch,
    classify_reservation,
    complete_reservation,
    dispatch_permitted,
    expire_reservation,
    quarantine_reservation,
    reopen_reservation,
    reservation_record_from_mapping,
    reservation_record_to_mapping,
)
from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import (
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)

_NOW = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_DIGEST = "sha256:" + "b" * 64


def _identity(
    *,
    idempotency_key: str = "example-idempotency",
    action_digest: str = "sha256:" + "1" * 64,
    path: ExecutionPath = ExecutionPath.DIRECT_API,
    owner_reference_digest: str = "sha256:" + "2" * 64,
    attempt: int = 1,
    target_ref: str = "resource/example",
    acquired_at: datetime = _NOW,
) -> IdempotencyReservationIdentity:
    request = ResourceLockAcquisitionRequest.create(
        target_ref=target_ref,
        action_digest=action_digest,
        attempt=attempt,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision=_SOURCE_REVISION,
    )
    receipt = ResourceLockAcquisitionReceipt.create(
        lock_key=request.lock_key,
        target_digest=request.target_digest,
        action_digest=request.action_digest,
        attempt=request.attempt,
        provider_id="local-resource-lock",
        provider_version="1.0.0",
        producer_id=request.producer_id,
        producer_version=request.producer_version,
        owner_token_digest=owner_reference_digest,
        fencing_generation=None,
        session_identity="session:example",
        provider_attestation_digest="sha256:" + "3" * 64,
        trust_anchor_id="fdai:local-test-only",
        acquired_at=acquired_at,
        valid_until=None,
        source_revision=request.source_revision,
        request_digest=request.request_digest,
    )
    return IdempotencyReservationIdentity.create(
        idempotency_key=idempotency_key,
        action_digest=action_digest,
        execution_path=path,
        execution_fingerprint="4" * 64,
        source_revision=_SOURCE_REVISION,
        acquisition_receipt=receipt,
    )


def _reserved() -> IdempotencyReservationRecord:
    return IdempotencyReservationRecord.create_reserved(
        identity=_identity(),
        reserved_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=10),
    )


def test_reserve_dispatch_and_terminal_transition_are_monotonic() -> None:
    reserved = _reserved()
    in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))
    terminal = complete_reservation(
        in_flight,
        at=_NOW + timedelta(seconds=2),
        terminal_outcome_digest="sha256:" + "5" * 64,
        authoritative_status_digest="sha256:" + "6" * 64,
    )

    assert reserved.state is ReservationState.RESERVED
    assert in_flight.state is ReservationState.IN_FLIGHT
    assert terminal.state is ReservationState.TERMINAL
    assert [reserved.revision, in_flight.revision, terminal.revision] == [1, 2, 3]
    assert terminal.execution_authority is False
    assert terminal.effect_verified is False


def test_expired_in_flight_becomes_unknown_and_cannot_redispatch() -> None:
    in_flight = begin_dispatch(_reserved(), at=_NOW + timedelta(seconds=1))
    unknown = expire_reservation(in_flight, at=_NOW + timedelta(seconds=10))

    assert unknown.state is ReservationState.OUTCOME_UNKNOWN
    assert unknown.evidence_kind is ReservationEvidenceKind.LEASE_EXPIRED
    assert dispatch_permitted(unknown, at=_NOW + timedelta(seconds=11)) is False
    with pytest.raises(ValueError, match="not eligible"):
        begin_dispatch(unknown, at=_NOW + timedelta(seconds=11))


def test_abandoned_requires_authoritative_proof_dispatch_never_began() -> None:
    reserved = _reserved()
    with pytest.raises(ValueError, match="requires proof"):
        expire_reservation(reserved, at=reserved.lease_expires_at)

    abandoned = expire_reservation(
        reserved,
        at=reserved.lease_expires_at,
        dispatch_never_began_digest=_DIGEST,
    )
    assert abandoned.state is ReservationState.ABANDONED
    assert abandoned.dispatch_started_at is None
    assert dispatch_permitted(abandoned, at=reserved.lease_expires_at) is False


def test_unknown_requires_authoritative_terminal_resolution() -> None:
    unknown = expire_reservation(
        begin_dispatch(_reserved(), at=_NOW + timedelta(seconds=1)),
        at=_NOW + timedelta(seconds=10),
    )
    resolved = complete_reservation(
        unknown,
        at=_NOW + timedelta(seconds=11),
        terminal_outcome_digest="sha256:" + "7" * 64,
        authoritative_status_digest="sha256:" + "8" * 64,
        irrevocable_non_acceptance=True,
    )

    assert resolved.state is ReservationState.TERMINAL
    assert resolved.evidence_kind is ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE


def test_duplicate_same_and_conflict_are_distinct() -> None:
    existing = _reserved()
    same = _identity()
    conflict = _identity(action_digest="sha256:" + "9" * 64)
    other_key = _identity(idempotency_key="other")

    assert classify_reservation(None, same) is ReservationMatch.ACQUIRED
    assert classify_reservation(existing, same) is ReservationMatch.DUPLICATE_SAME
    assert classify_reservation(existing, conflict) is ReservationMatch.CONFLICT
    assert classify_reservation(existing, other_key) is ReservationMatch.ACQUIRED


def test_transition_receipt_binds_cas_revision_and_readback() -> None:
    record = _reserved()
    receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=record,
        expected_prior_revision=0,
        store_receipt_digest="sha256:" + "a" * 64,
        recorded_at=_NOW,
    )

    assert receipt.execution_authority is False
    assert receipt.effect_verified is False
    with pytest.raises(ValueError, match="revision mismatched"):
        replace(receipt, expected_prior_revision=1)
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(receipt, receipt_digest="sha256:" + "0" * 64)
    result = IdempotencyReservationReserveResult(
        candidate_identity=record.identity,
        match=ReservationMatch.ACQUIRED,
        observed_record=record,
        transition_receipt=receipt,
    )
    assert result.observed_record is record
    with pytest.raises(ValueError, match="mismatched its candidate"):
        IdempotencyReservationReserveResult(
            candidate_identity=_identity(path=ExecutionPath.TOOL_CALL),
            match=ReservationMatch.DUPLICATE_SAME,
            observed_record=record,
            transition_receipt=None,
        )


def test_identity_rejects_acquisition_and_action_substitution() -> None:
    identity = _identity()
    with pytest.raises(ValueError, match="acquisition context mismatched"):
        replace(identity, action_digest="sha256:" + "9" * 64)
    with pytest.raises(ValueError, match="identity digest mismatched"):
        replace(identity, idempotency_key="other")


def test_acquisition_substitution_is_a_conflict() -> None:
    existing = _reserved()
    replacement = _identity(
        owner_reference_digest="sha256:" + "9" * 64,
    )
    assert classify_reservation(existing, replacement) is ReservationMatch.CONFLICT


def test_invalid_state_shape_and_time_fail_closed() -> None:
    reserved = _reserved()
    with pytest.raises(ValueError, match="later-phase evidence"):
        replace(
            reserved,
            evidence_kind=ReservationEvidenceKind.LEASE_EXPIRED,
            evidence_digest=_DIGEST,
        )
    with pytest.raises(ValueError, match="lease has not expired"):
        expire_reservation(reserved, at=_NOW + timedelta(seconds=9))
    with pytest.raises(ValueError, match="predates current state"):
        complete_reservation(
            begin_dispatch(reserved, at=_NOW + timedelta(seconds=1)),
            at=_NOW,
            terminal_outcome_digest=_DIGEST,
            authoritative_status_digest=_DIGEST,
        )


def test_unknown_state_rejects_backdated_continuity_evidence() -> None:
    in_flight = begin_dispatch(_reserved(), at=_NOW + timedelta(seconds=1))
    lease_expired = expire_reservation(in_flight, at=_NOW + timedelta(seconds=10))
    with pytest.raises(ValueError, match="lease-expired.*predates expiry"):
        replace(
            lease_expired,
            state_changed_at=lease_expired.lease_expires_at - timedelta(microseconds=1),
        )

    continuity_unknown = quarantine_reservation(
        in_flight,
        at=_NOW + timedelta(seconds=2),
        continuity_evidence_digest=_DIGEST,
    )
    with pytest.raises(ValueError, match="continuity evidence predates dispatch"):
        replace(continuity_unknown, state_changed_at=_NOW)


def test_transition_receipt_requires_exact_predecessor_and_legal_edge() -> None:
    reserved = _reserved()
    in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))
    receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=reserved,
        record=in_flight,
        expected_prior_revision=1,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW + timedelta(seconds=1),
    )
    assert receipt.prior_record is reserved
    with pytest.raises(ValueError, match="requires its predecessor"):
        replace(receipt, prior_record=None)
    abandoned = expire_reservation(
        reserved,
        at=reserved.lease_expires_at,
        dispatch_never_began_digest=_DIGEST,
    )
    terminal = complete_reservation(
        in_flight,
        at=_NOW + timedelta(seconds=2),
        terminal_outcome_digest="sha256:" + "7" * 64,
        authoritative_status_digest="sha256:" + "8" * 64,
    )
    with pytest.raises(ValueError, match="transition edge is invalid"):
        IdempotencyReservationTransitionReceipt.create(
            prior_record=abandoned,
            expected_prior_revision=2,
            record=terminal,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW + timedelta(seconds=10),
        )


def test_transition_receipt_rejects_predecessor_revision_and_time_mismatch() -> None:
    reserved = _reserved()
    in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))
    receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=reserved,
        record=in_flight,
        expected_prior_revision=reserved.revision,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW + timedelta(seconds=1),
    )
    wrong_revision = reservation_model._build_record(  # noqa: SLF001
        identity=reserved.identity,
        state=ReservationState.RESERVED,
        revision=2,
        reserved_at=reserved.reserved_at,
        lease_expires_at=reserved.lease_expires_at,
        state_changed_at=reserved.state_changed_at,
    )

    with pytest.raises(ValueError, match="predecessor mismatched"):
        replace(receipt, prior_record=wrong_revision)
    with pytest.raises(ValueError, match="predates its predecessor"):
        replace(
            receipt,
            recorded_at=reserved.state_changed_at - timedelta(microseconds=1),
        )


def test_transition_validation_rejects_identity_and_attempt_substitution() -> None:
    reserved = _reserved()
    abandoned = expire_reservation(
        reserved,
        at=reserved.lease_expires_at,
        dispatch_never_began_digest=_DIGEST,
    )
    changed_operation = reservation_model._build_record(  # noqa: SLF001
        identity=_identity(
            attempt=2,
            target_ref="resource/other",
            acquired_at=_NOW + timedelta(seconds=10),
        ),
        state=ReservationState.RESERVED,
        revision=3,
        reserved_at=_NOW + timedelta(seconds=11),
        lease_expires_at=_NOW + timedelta(seconds=20),
        state_changed_at=_NOW + timedelta(seconds=11),
    )
    repeated_attempt = reservation_model._build_record(  # noqa: SLF001
        identity=_identity(
            acquired_at=_NOW + timedelta(seconds=10),
        ),
        state=ReservationState.RESERVED,
        revision=3,
        reserved_at=_NOW + timedelta(seconds=11),
        lease_expires_at=_NOW + timedelta(seconds=20),
        state_changed_at=_NOW + timedelta(seconds=11),
    )

    with pytest.raises(ValueError, match="changes the stable operation"):
        reservation_model.validate_reservation_transition(abandoned, changed_operation)
    with pytest.raises(ValueError, match="attempt MUST increase"):
        reservation_model.validate_reservation_transition(abandoned, repeated_attempt)

    substituted_in_flight = reservation_model._build_record(  # noqa: SLF001
        identity=_identity(target_ref="resource/other"),
        state=ReservationState.IN_FLIGHT,
        revision=2,
        reserved_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=10),
        state_changed_at=_NOW + timedelta(seconds=1),
        dispatch_started_at=_NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="transition identity changed"):
        reservation_model.validate_reservation_transition(
            reserved,
            substituted_in_flight,
        )


def test_reservation_factories_reject_naive_time_and_accept_observed_duplicate() -> None:
    with pytest.raises(ValueError, match="MUST include a timezone"):
        IdempotencyReservationRecord.create_reserved(
            identity=_identity(),
            reserved_at=_NOW.replace(tzinfo=None),
            lease_expires_at=_NOW + timedelta(seconds=10),
        )

    observed = _reserved()
    result = IdempotencyReservationReserveResult(
        candidate_identity=_identity(),
        match=ReservationMatch.DUPLICATE_SAME,
        observed_record=observed,
        transition_receipt=None,
    )
    assert result.observed_record is observed


def test_transition_receipt_rejects_lease_rewrite() -> None:
    reserved = _reserved()
    rewritten_reserved = IdempotencyReservationRecord.create_reserved(
        identity=reserved.identity,
        reserved_at=_NOW + timedelta(seconds=1),
        lease_expires_at=_NOW + timedelta(seconds=20),
    )
    rewritten = begin_dispatch(
        rewritten_reserved,
        at=_NOW + timedelta(seconds=2),
    )
    with pytest.raises(ValueError):
        IdempotencyReservationTransitionReceipt.create(
            prior_record=reserved,
            record=rewritten,
            expected_prior_revision=1,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW + timedelta(seconds=1),
        )


def test_transition_receipt_rejects_dispatch_time_substitution() -> None:
    reserved = _reserved()
    prior = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))
    substituted_dispatch = begin_dispatch(
        reserved,
        at=_NOW + timedelta(seconds=2),
    )
    terminal = complete_reservation(
        substituted_dispatch,
        at=_NOW + timedelta(seconds=3),
        terminal_outcome_digest="sha256:" + "7" * 64,
        authoritative_status_digest="sha256:" + "8" * 64,
    )
    with pytest.raises(ValueError, match="rewrote dispatch time"):
        IdempotencyReservationTransitionReceipt.create(
            prior_record=prior,
            record=terminal,
            expected_prior_revision=prior.revision,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW + timedelta(seconds=3),
        )


def test_authoritative_non_dispatch_allows_higher_attempt_recovery() -> None:
    reserved = _reserved()
    abandoned = expire_reservation(
        reserved,
        at=reserved.lease_expires_at,
        dispatch_never_began_digest=_DIGEST,
    )
    recovered = reopen_reservation(
        abandoned,
        candidate_identity=_identity(
            attempt=2,
            acquired_at=_NOW + timedelta(seconds=10),
        ),
        reserved_at=_NOW + timedelta(seconds=11),
        lease_expires_at=_NOW + timedelta(seconds=20),
    )
    transition = IdempotencyReservationTransitionReceipt.create(
        prior_record=abandoned,
        record=recovered,
        expected_prior_revision=abandoned.revision,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW + timedelta(seconds=11),
    )

    assert recovered.state is ReservationState.RESERVED
    assert recovered.identity.acquisition_receipt.attempt == 2
    assert transition.record is recovered
    with pytest.raises(ValueError, match="changes the stable operation"):
        reopen_reservation(
            abandoned,
            candidate_identity=_identity(
                attempt=2,
                target_ref="resource/other",
                acquired_at=_NOW + timedelta(seconds=10),
            ),
            reserved_at=_NOW + timedelta(seconds=11),
            lease_expires_at=_NOW + timedelta(seconds=20),
        )


def test_terminal_and_recovery_cannot_predate_predecessor_state() -> None:
    in_flight = begin_dispatch(_reserved(), at=_NOW + timedelta(seconds=1))
    unknown = expire_reservation(
        in_flight,
        at=in_flight.lease_expires_at,
    )
    with pytest.raises(ValueError, match="predates current state"):
        complete_reservation(
            unknown,
            at=_NOW + timedelta(seconds=2),
            terminal_outcome_digest="sha256:" + "7" * 64,
            authoritative_status_digest="sha256:" + "8" * 64,
        )

    abandoned = expire_reservation(
        _reserved(),
        at=_NOW + timedelta(seconds=10),
        dispatch_never_began_digest=_DIGEST,
    )
    with pytest.raises(ValueError, match="predates its predecessor"):
        reopen_reservation(
            abandoned,
            candidate_identity=_identity(
                attempt=2,
                acquired_at=_NOW + timedelta(seconds=10),
            ),
            reserved_at=_NOW + timedelta(seconds=2),
            lease_expires_at=_NOW + timedelta(seconds=20),
        )


def test_reservation_cannot_predate_lock_acquisition() -> None:
    identity = _identity(acquired_at=_NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="predates its lock acquisition"):
        IdempotencyReservationRecord.create_reserved(
            identity=identity,
            reserved_at=_NOW,
            lease_expires_at=_NOW + timedelta(seconds=10),
        )


def test_transition_receipt_rejects_backdated_recovery_acquisition() -> None:
    predecessor = expire_reservation(
        _reserved(),
        at=_NOW + timedelta(seconds=10),
        dispatch_never_began_digest=_DIGEST,
    )
    reconstructed = reservation_model._build_record(  # noqa: SLF001
        identity=_identity(
            attempt=2,
            acquired_at=_NOW + timedelta(seconds=5),
        ),
        state=ReservationState.RESERVED,
        revision=predecessor.revision + 1,
        reserved_at=_NOW + timedelta(seconds=11),
        lease_expires_at=_NOW + timedelta(seconds=20),
        state_changed_at=_NOW + timedelta(seconds=11),
    )
    with pytest.raises(ValueError, match="recovery acquisition time is invalid"):
        IdempotencyReservationTransitionReceipt.create(
            prior_record=predecessor,
            record=reconstructed,
            expected_prior_revision=predecessor.revision,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW + timedelta(seconds=11),
        )


def test_reservation_record_mapping_round_trip_is_exact() -> None:
    record = expire_reservation(
        begin_dispatch(_reserved(), at=_NOW + timedelta(seconds=1)),
        at=_NOW + timedelta(seconds=10),
    )
    mapping = reservation_record_to_mapping(record)

    assert reservation_record_from_mapping(mapping) == record
    with pytest.raises(ValueError, match="fields are invalid"):
        reservation_record_from_mapping({**mapping, "unexpected": True})


def test_reservation_record_mapping_rejects_corruption() -> None:
    mapping = reservation_record_to_mapping(_reserved())
    identity = cast(dict[str, object], mapping["identity"])
    acquisition = cast(dict[str, object], identity["acquisition_receipt"])

    with pytest.raises(ValueError, match="digest mismatched"):
        reservation_record_from_mapping(
            {
                **mapping,
                "record_digest": "sha256:" + "0" * 64,
            }
        )
    with pytest.raises(ValueError, match="MUST be an ISO 8601 timestamp"):
        reservation_record_from_mapping(
            {
                **mapping,
                "reserved_at": "not-a-time",
            }
        )
    with pytest.raises(ValueError):
        reservation_record_from_mapping(
            {
                **mapping,
                "identity": {
                    **identity,
                    "acquisition_receipt": {
                        **acquisition,
                        "execution_authority": True,
                    },
                },
            }
        )


def test_reservation_record_mapping_rejects_invalid_field_types() -> None:
    mapping = reservation_record_to_mapping(_reserved())

    with pytest.raises(ValueError, match="exact record"):
        reservation_record_to_mapping(cast(IdempotencyReservationRecord, object()))

    corruptions: tuple[tuple[tuple[str, ...], object, str], ...] = (
        (("identity",), None, "MUST be an object"),
        (("schema_version",), 1, "MUST be a string"),
        (("schema_version",), "2.0.0", "schema version is unsupported"),
        (("evidence_digest",), 1, "string or null"),
        (("revision",), "1", "MUST be an integer"),
        (("state",), "invalid", "state is invalid"),
        (("identity", "acquisition_receipt", "fencing_generation"), "1", "integer or null"),
    )
    for path, value, message in corruptions:
        corrupted = copy.deepcopy(mapping)
        target = corrupted
        for segment in path[:-1]:
            target = cast(dict[str, object], target[segment])
        target[path[-1]] = value
        with pytest.raises(ValueError, match=message):
            reservation_record_from_mapping(corrupted)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda identity: replace(
                identity,
                schema_version=cast(Literal["1.0.0"], "2.0.0"),
            ),
            "identity schema",
        ),
        (
            lambda identity: replace(
                identity,
                execution_authority=cast(Literal[False], True),
            ),
            "MUST NOT grant authority",
        ),
        (lambda identity: replace(identity, idempotency_key=""), "canonical and bounded"),
        (lambda identity: replace(identity, action_digest="invalid"), "MUST be SHA-256"),
        (
            lambda identity: replace(
                identity,
                execution_path=cast(ExecutionPath, "direct_api"),
            ),
            "execution path is invalid",
        ),
        (
            lambda identity: replace(identity, execution_fingerprint="A" * 64),
            "lowercase SHA-256",
        ),
        (
            lambda identity: replace(identity, source_revision="main"),
            "source revision MUST be canonical",
        ),
        (
            lambda identity: replace(
                identity,
                acquisition_receipt=cast(ResourceLockAcquisitionReceipt, object()),
            ),
            "exact acquisition receipt",
        ),
    ),
)
def test_identity_boundary_validation_fails_closed(
    mutate: Callable[[IdempotencyReservationIdentity], IdempotencyReservationIdentity],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        mutate(_identity())


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda record: replace(
                record,
                schema_version=cast(Literal["1.0.0"], "2.0.0"),
            ),
            "record schema",
        ),
        (
            lambda record: replace(
                record,
                effect_verified=cast(Literal[False], True),
            ),
            "MUST NOT grant authority",
        ),
        (
            lambda record: replace(
                record,
                identity=cast(IdempotencyReservationIdentity, object()),
            ),
            "exact identity",
        ),
        (
            lambda record: replace(
                record,
                state=cast(ReservationState, "reserved"),
            ),
            "state is invalid",
        ),
        (lambda record: replace(record, revision=0), "revision MUST be positive"),
        (
            lambda record: replace(record, owner_reference_digest="invalid"),
            "MUST be SHA-256",
        ),
        (
            lambda record: replace(
                record,
                owner_reference_digest="sha256:" + "9" * 64,
            ),
            "owner mismatched",
        ),
        (
            lambda record: replace(
                record,
                reserved_at=datetime(2026, 9, 10, 8, 0),
            ),
            "normalized to UTC",
        ),
        (
            lambda record: replace(
                record,
                lease_expires_at=datetime(2026, 9, 10, 8, 1),
            ),
            "normalized to UTC",
        ),
        (
            lambda record: replace(
                record,
                state_changed_at=datetime(2026, 9, 10, 8, 0),
            ),
            "normalized to UTC",
        ),
        (lambda record: replace(record, lease_expires_at=_NOW), "lease MUST follow"),
        (
            lambda record: replace(
                record,
                reserved_at=_NOW - timedelta(seconds=1),
            ),
            "predates its lock acquisition",
        ),
        (
            lambda record: replace(
                record,
                state_changed_at=_NOW - timedelta(seconds=1),
            ),
            "predates reservation",
        ),
        (
            lambda record: replace(
                record,
                dispatch_started_at=datetime(2026, 9, 10, 8, 0),
            ),
            "normalized to UTC",
        ),
        (
            lambda record: replace(
                record,
                dispatch_started_at=_NOW - timedelta(seconds=1),
            ),
            "cannot predate",
        ),
        (
            lambda record: replace(
                record,
                evidence_kind=cast(ReservationEvidenceKind, "lease_expired"),
            ),
            "evidence kind is invalid",
        ),
        (
            lambda record: replace(record, evidence_digest="invalid"),
            "MUST be SHA-256",
        ),
        (
            lambda record: replace(record, terminal_outcome_digest="invalid"),
            "MUST be SHA-256",
        ),
    ),
)
def test_record_boundary_validation_fails_closed(
    mutate: Callable[[IdempotencyReservationRecord], IdempotencyReservationRecord],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        mutate(_reserved())


def test_every_state_shape_and_minimum_revision_is_validated() -> None:
    reserved = _reserved()
    in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))
    abandoned = expire_reservation(
        reserved,
        at=reserved.lease_expires_at,
        dispatch_never_began_digest=_DIGEST,
    )
    unknown = expire_reservation(in_flight, at=in_flight.lease_expires_at)
    terminal = complete_reservation(
        in_flight,
        at=_NOW + timedelta(seconds=2),
        terminal_outcome_digest="sha256:" + "7" * 64,
        authoritative_status_digest="sha256:" + "8" * 64,
    )

    invalid_shapes = (
        (replace, reserved, {"state_changed_at": _NOW + timedelta(seconds=1)}),
        (replace, in_flight, {"dispatch_started_at": None}),
        (replace, abandoned, {"evidence_digest": None}),
        (replace, unknown, {"evidence_digest": None}),
        (replace, terminal, {"terminal_outcome_digest": None}),
    )
    for mutate, record, changes in invalid_shapes:
        with pytest.raises(ValueError):
            mutate(record, **changes)
    with pytest.raises(ValueError, match="revision is impossible"):
        replace(in_flight, revision=1)


def test_lifecycle_rejects_unsafe_terminal_and_recovery_paths() -> None:
    reserved = _reserved()
    in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))
    terminal = complete_reservation(
        in_flight,
        at=_NOW + timedelta(seconds=2),
        terminal_outcome_digest="sha256:" + "7" * 64,
        authoritative_status_digest="sha256:" + "8" * 64,
    )
    abandoned = expire_reservation(
        reserved,
        at=reserved.lease_expires_at,
        dispatch_never_began_digest=_DIGEST,
    )

    with pytest.raises(ValueError, match="cannot be expired"):
        expire_reservation(terminal, at=terminal.lease_expires_at)
    with pytest.raises(ValueError, match="not awaiting"):
        complete_reservation(
            reserved,
            at=_NOW + timedelta(seconds=1),
            terminal_outcome_digest=_DIGEST,
            authoritative_status_digest=_DIGEST,
        )
    with pytest.raises(ValueError, match="no safe recovery evidence"):
        reopen_reservation(
            in_flight,
            candidate_identity=_identity(attempt=2),
            reserved_at=_NOW + timedelta(seconds=2),
            lease_expires_at=_NOW + timedelta(seconds=20),
        )
    with pytest.raises(ValueError, match="attempt MUST increase"):
        reopen_reservation(
            abandoned,
            candidate_identity=_identity(acquired_at=abandoned.state_changed_at),
            reserved_at=abandoned.state_changed_at,
            lease_expires_at=_NOW + timedelta(seconds=20),
        )
    with pytest.raises(ValueError, match="acquisition time is invalid"):
        reopen_reservation(
            abandoned,
            candidate_identity=_identity(
                attempt=2,
                acquired_at=_NOW + timedelta(seconds=12),
            ),
            reserved_at=_NOW + timedelta(seconds=11),
            lease_expires_at=_NOW + timedelta(seconds=20),
        )


def test_reservation_factories_reject_subclasses() -> None:
    identity = _identity()
    record = _reserved()

    class IdentitySubclass(IdempotencyReservationIdentity):
        pass

    class RecordSubclass(IdempotencyReservationRecord):
        pass

    class TransitionSubclass(IdempotencyReservationTransitionReceipt):
        pass

    with pytest.raises(TypeError, match="identity does not support subclasses"):
        IdentitySubclass.create(
            idempotency_key=identity.idempotency_key,
            action_digest=identity.action_digest,
            execution_path=identity.execution_path,
            execution_fingerprint=identity.execution_fingerprint,
            source_revision=identity.source_revision,
            acquisition_receipt=identity.acquisition_receipt,
        )
    with pytest.raises(TypeError, match="record does not support subclasses"):
        RecordSubclass.create_reserved(
            identity=identity,
            reserved_at=record.reserved_at,
            lease_expires_at=record.lease_expires_at,
        )
    with pytest.raises(TypeError, match="receipt does not support subclasses"):
        TransitionSubclass.create(
            prior_record=None,
            record=record,
            expected_prior_revision=0,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )


def test_transition_receipt_boundary_validation_fails_closed() -> None:
    reserved = _reserved()
    in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=1))
    initial = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=reserved,
        expected_prior_revision=0,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    transition = IdempotencyReservationTransitionReceipt.create(
        prior_record=reserved,
        record=in_flight,
        expected_prior_revision=reserved.revision,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW + timedelta(seconds=1),
    )
    invalid_receipts: tuple[Callable[[], object], ...] = (
        lambda: replace(
            initial,
            schema_version=cast(Literal["1.0.0"], "2.0.0"),
        ),
        lambda: replace(
            initial,
            execution_authority=cast(Literal[False], True),
        ),
        lambda: replace(
            initial,
            record=cast(IdempotencyReservationRecord, object()),
        ),
        lambda: replace(initial, expected_prior_revision=-1),
        lambda: replace(initial, prior_record=reserved),
        lambda: replace(
            transition,
            prior_record=replace(reserved, revision=2),
        ),
        lambda: replace(initial, store_receipt_digest="invalid"),
        lambda: replace(initial, recorded_at=datetime(2026, 9, 10, 8, 0)),
        lambda: replace(
            transition,
            recorded_at=_NOW,
        ),
    )
    for build_invalid in invalid_receipts:
        with pytest.raises(ValueError):
            build_invalid()


def test_reserve_result_boundary_validation_fails_closed() -> None:
    reserved = _reserved()
    receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=reserved,
        expected_prior_revision=0,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    invalid_results: tuple[Callable[[], object], ...] = (
        lambda: IdempotencyReservationReserveResult(
            candidate_identity=reserved.identity,
            match=cast(ReservationMatch, "acquired"),
            observed_record=reserved,
            transition_receipt=receipt,
        ),
        lambda: IdempotencyReservationReserveResult(
            candidate_identity=cast(IdempotencyReservationIdentity, object()),
            match=ReservationMatch.ACQUIRED,
            observed_record=reserved,
            transition_receipt=receipt,
        ),
        lambda: IdempotencyReservationReserveResult(
            candidate_identity=reserved.identity,
            match=ReservationMatch.ACQUIRED,
            observed_record=cast(IdempotencyReservationRecord, object()),
            transition_receipt=receipt,
        ),
        lambda: IdempotencyReservationReserveResult(
            candidate_identity=reserved.identity,
            match=ReservationMatch.ACQUIRED,
            observed_record=reserved,
            transition_receipt=None,
        ),
        lambda: IdempotencyReservationReserveResult(
            candidate_identity=reserved.identity,
            match=ReservationMatch.DUPLICATE_SAME,
            observed_record=reserved,
            transition_receipt=receipt,
        ),
    )
    for build_invalid in invalid_results:
        with pytest.raises(ValueError):
            build_invalid()


def test_transition_validation_rejects_backdating_and_missing_recovery_evidence() -> None:
    reserved = _reserved()
    later_in_flight = begin_dispatch(reserved, at=_NOW + timedelta(seconds=5))
    earlier_terminal = complete_reservation(
        begin_dispatch(reserved, at=_NOW + timedelta(seconds=1)),
        at=_NOW + timedelta(seconds=2),
        terminal_outcome_digest="sha256:" + "7" * 64,
        authoritative_status_digest="sha256:" + "8" * 64,
    )
    with pytest.raises(ValueError, match="transition is backdated"):
        reservation_model._validate_transition(  # noqa: SLF001
            later_in_flight,
            earlier_terminal,
        )

    terminal = complete_reservation(
        begin_dispatch(reserved, at=_NOW + timedelta(seconds=1)),
        at=_NOW + timedelta(seconds=2),
        terminal_outcome_digest="sha256:" + "7" * 64,
        authoritative_status_digest="sha256:" + "8" * 64,
    )
    candidate = _identity(
        attempt=2,
        acquired_at=_NOW + timedelta(seconds=2),
    )
    recovered = reservation_model._build_record(  # noqa: SLF001
        identity=candidate,
        state=ReservationState.RESERVED,
        revision=terminal.revision + 1,
        reserved_at=_NOW + timedelta(seconds=3),
        lease_expires_at=_NOW + timedelta(seconds=20),
        state_changed_at=_NOW + timedelta(seconds=3),
    )
    with pytest.raises(ValueError, match="lacks non-dispatch evidence"):
        reservation_model._validate_transition(terminal, recovered)  # noqa: SLF001


@pytest.mark.parametrize("idempotency_key", (" padded", "padded ", "x" * 513))
def test_identity_rejects_noncanonical_bounded_keys(idempotency_key: str) -> None:
    with pytest.raises(ValueError, match="canonical and bounded"):
        _identity(idempotency_key=idempotency_key)


def test_digest_normalization_preserves_sequence_order() -> None:
    assert reservation_model._normalize_digest_value(  # noqa: SLF001
        (ReservationState.RESERVED, _NOW)
    ) == ["reserved", _NOW.isoformat()]
