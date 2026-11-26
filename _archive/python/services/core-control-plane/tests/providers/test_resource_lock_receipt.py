"""Provider-neutral lock acquisition and live ownership contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from inspect import signature

import pytest
from fdai.core.executor.lock import ResourceLockManager
from fdai.shared.providers.resource_lock import (
    EvidenceResourceLock,
    HeldResourceLock,
    HeldResourceLockLifecycle,
    LiveLockOwnershipAssessment,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
    require_current_lock_ownership,
    require_evidence_resource_lock,
    resource_lock_key,
    resource_lock_target_digest,
)

_NOW = datetime(2026, 9, 10, 5, 0, tzinfo=UTC)


def _request() -> ResourceLockAcquisitionRequest:
    return ResourceLockAcquisitionRequest.create(
        target_ref="example",
        action_digest="sha256:" + "2" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )


def _values() -> dict[str, object]:
    request = _request()
    return {
        "lock_key": "fdai:resource:example",
        "target_digest": request.target_digest,
        "action_digest": request.action_digest,
        "attempt": 1,
        "provider_id": "postgres-advisory-lock",
        "provider_version": "1.0.0",
        "producer_id": "fdai.core.executor",
        "producer_version": "1.0.0",
        "owner_token_digest": "sha256:" + "3" * 64,
        "fencing_generation": 4,
        "session_identity": None,
        "provider_attestation_digest": "sha256:" + "4" * 64,
        "trust_anchor_id": "postgres:primary",
        "acquired_at": _NOW,
        "valid_until": _NOW + timedelta(minutes=1),
        "source_revision": "commit:" + "a" * 40,
        "request_digest": request.request_digest,
    }


def _receipt(**overrides: object) -> ResourceLockAcquisitionReceipt:
    values = _values()
    values.update(overrides)
    return ResourceLockAcquisitionReceipt.create(**values)


def _assessment(
    receipt: ResourceLockAcquisitionReceipt,
    **overrides: object,
) -> LiveLockOwnershipAssessment:
    values: dict[str, object] = {
        "current_fencing_generation": 4,
        "current_session_identity": None,
        "verifier_id": "postgres-lock-readback",
        "verifier_version": "1.0.0",
        "trust_anchor_id": receipt.trust_anchor_id,
        "provider_attestation_digest": "sha256:" + "5" * 64,
        "evaluated_at": _NOW + timedelta(seconds=1),
        "valid_until": _NOW + timedelta(seconds=2),
    }
    values.update(overrides)
    return LiveLockOwnershipAssessment.create(receipt, **values)  # type: ignore[arg-type]


def test_lease_and_session_receipts_are_canonical_and_authority_free() -> None:
    lease = _receipt(acquired_at=_NOW.astimezone(timezone(timedelta(hours=9))))
    session = _receipt(
        fencing_generation=None,
        session_identity="session:example",
        valid_until=None,
    )

    assert lease.acquired_at == _NOW
    assert lease.execution_authority is False
    assert session.execution_authority is False
    assert lease.receipt_digest != session.receipt_digest


def test_live_assessment_requires_current_fence_and_trust_anchor() -> None:
    receipt = _receipt()
    current = LiveLockOwnershipAssessment.create(
        receipt,
        current_fencing_generation=4,
        current_session_identity=None,
        verifier_id="postgres-lock-readback",
        verifier_version="1.0.0",
        trust_anchor_id=receipt.trust_anchor_id,
        provider_attestation_digest="sha256:" + "5" * 64,
        evaluated_at=_NOW + timedelta(seconds=1),
        valid_until=_NOW + timedelta(seconds=2),
    )
    stale = LiveLockOwnershipAssessment.create(
        receipt,
        current_fencing_generation=5,
        current_session_identity=None,
        verifier_id="postgres-lock-readback",
        verifier_version="1.0.0",
        trust_anchor_id="postgres:other",
        provider_attestation_digest="sha256:" + "5" * 64,
        evaluated_at=_NOW + timedelta(seconds=1),
        valid_until=_NOW + timedelta(seconds=2),
    )

    assert current.eligible is True
    assert current.execution_authority is False
    assert stale.eligible is False
    assert set(stale.rejection_reasons) == {
        LockOwnershipRejectionReason.FENCE_MISMATCH,
        LockOwnershipRejectionReason.TRUST_ANCHOR_MISMATCH,
    }


def test_current_ownership_guard_rejects_historical_stale_and_future_evidence() -> None:
    receipt = _receipt()
    assessment = _assessment(receipt)
    assert (
        require_current_lock_ownership(
            assessment,
            observed_at=assessment.evaluated_at,
        )
        is assessment
    )
    with pytest.raises(ValueError, match="historical lock acquisition"):
        require_current_lock_ownership(receipt, observed_at=assessment.evaluated_at)
    with pytest.raises(ValueError, match="not yet current"):
        require_current_lock_ownership(
            assessment,
            observed_at=assessment.evaluated_at - timedelta(microseconds=1),
        )
    with pytest.raises(ValueError, match="is stale"):
        require_current_lock_ownership(
            assessment,
            observed_at=assessment.valid_until,
        )


def test_current_ownership_guard_rejects_ineligible_assessment() -> None:
    assessment = _assessment(_receipt(), current_fencing_generation=5)
    with pytest.raises(ValueError, match="is ineligible"):
        require_current_lock_ownership(
            assessment,
            observed_at=assessment.evaluated_at,
        )


def test_lock_evidence_replay_is_deterministic() -> None:
    first_receipt = _receipt()
    second_receipt = _receipt()
    assert first_receipt == second_receipt
    assert _assessment(first_receipt) == _assessment(second_receipt)


def test_lock_target_digest_is_canonical() -> None:
    assert resource_lock_target_digest("resource/example").startswith("sha256:")
    with pytest.raises(ValueError, match="MUST be canonical"):
        resource_lock_target_digest(" resource/example ")


def test_acquisition_request_is_canonical_deterministic_and_authority_free() -> None:
    first = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "2" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )
    second = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "2" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )

    assert first == second
    assert first.target_ref == "resource/example"
    assert first.lock_key == resource_lock_key("resource/example")
    assert first.target_digest == resource_lock_target_digest("resource/example")
    assert first.execution_authority is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_ref", " resource/example "),
        ("action_digest", "not-a-digest"),
        ("attempt", 0),
        ("attempt", True),
        ("producer_id", " "),
        ("producer_version", ""),
        ("source_revision", "main"),
    ],
)
def test_acquisition_request_rejects_noncanonical_input(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "target_ref": "resource/example",
        "action_digest": "sha256:" + "2" * 64,
        "attempt": 1,
        "producer_id": "fdai.core.executor",
        "producer_version": "1.0.0",
        "source_revision": "commit:" + "a" * 40,
    }
    values[field] = value
    with pytest.raises(ValueError):
        ResourceLockAcquisitionRequest.create(**values)  # type: ignore[arg-type]


def test_held_lock_lifecycle_becomes_permanently_inert() -> None:
    lifecycle = HeldResourceLockLifecycle(_request(), _receipt())
    lifecycle.require_active()
    lifecycle.deactivate()
    with pytest.raises(RuntimeError, match="no longer active"):
        lifecycle.require_active()
    with pytest.raises(AttributeError):
        lifecycle._active = True
    lifecycle.deactivate()
    with pytest.raises(RuntimeError, match="no longer active"):
        lifecycle.require_active()


def test_evidenced_lock_assessment_signature_uses_adapter_owned_time() -> None:
    assert tuple(signature(HeldResourceLock.assess_ownership).parameters) == ("self",)


def test_evidenced_lock_resolution_has_no_legacy_or_production_fallback() -> None:
    class TestEvidenceLock:
        production_eligible = False

        def acquire_evidenced(self, request: ResourceLockAcquisitionRequest) -> object:
            raise NotImplementedError

    local = TestEvidenceLock()
    assert isinstance(local, EvidenceResourceLock)
    assert require_evidence_resource_lock(local, production=False) is local
    with pytest.raises(RuntimeError, match="not production eligible"):
        require_evidence_resource_lock(local, production=True)
    manager = ResourceLockManager()
    assert require_evidence_resource_lock(manager, production=False) is manager
    with pytest.raises(RuntimeError, match="not production eligible"):
        require_evidence_resource_lock(manager, production=True)
    with pytest.raises(RuntimeError, match="unavailable"):
        require_evidence_resource_lock(object(), production=False)


def test_held_lock_lifecycle_rejects_request_receipt_substitution() -> None:
    request = ResourceLockAcquisitionRequest.create(
        target_ref="example",
        action_digest="sha256:" + "9" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )
    receipt = _receipt()
    with pytest.raises(ValueError, match="does not match"):
        HeldResourceLockLifecycle(request, receipt)


def test_session_assessment_rejects_excessive_ttl() -> None:
    receipt = _receipt(
        fencing_generation=None,
        session_identity="session:example",
        valid_until=None,
    )
    with pytest.raises(ValueError, match="maximum TTL"):
        _assessment(
            receipt,
            current_fencing_generation=None,
            current_session_identity="session:example",
            valid_until=_NOW + timedelta(seconds=7),
        )


def test_request_rejects_substituted_target_identity() -> None:
    request = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "2" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )
    with pytest.raises(ValueError, match="target identity mismatched"):
        replace(request, target_ref="resource/other")


def test_canonical_lock_key_preserves_existing_long_target_support() -> None:
    target_ref = "resource/" + "a" * 1024
    lock_key = resource_lock_key(target_ref)
    assert lock_key == f"fdai:resource:{target_ref}"
    assert _receipt(lock_key=lock_key).lock_key == lock_key


@pytest.mark.parametrize(
    "overrides",
    [
        {"attempt": 0},
        {"fencing_generation": None},
        {"session_identity": "session", "valid_until": _NOW + timedelta(minutes=1)},
        {"valid_until": _NOW},
        {"source_revision": "main"},
        {"owner_token_digest": "raw-token"},
        {"provider_attestation_digest": ""},
    ],
)
def test_invalid_receipt_classes_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _receipt(**overrides)


def test_receipt_and_assessment_digest_tampering_fails_closed() -> None:
    receipt = _receipt()
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(receipt, receipt_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(receipt, request_digest="sha256:" + "9" * 64)

    assessment = LiveLockOwnershipAssessment.create(
        receipt,
        current_fencing_generation=4,
        current_session_identity=None,
        verifier_id="postgres-lock-readback",
        verifier_version="1.0.0",
        trust_anchor_id=receipt.trust_anchor_id,
        provider_attestation_digest="sha256:" + "5" * 64,
        evaluated_at=_NOW + timedelta(seconds=1),
        valid_until=_NOW + timedelta(seconds=2),
    )
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(assessment, assessment_digest="sha256:" + "0" * 64)


def test_live_assessment_cannot_predate_acquisition_or_outlive_lease() -> None:
    receipt = _receipt(valid_until=_NOW + timedelta(seconds=2))
    with pytest.raises(ValueError, match="cannot predate"):
        _assessment(
            receipt,
            evaluated_at=receipt.acquired_at - timedelta(microseconds=1),
            valid_until=receipt.acquired_at + timedelta(microseconds=1),
        )
    assert receipt.valid_until is not None
    outliving = _assessment(
        receipt,
        valid_until=receipt.valid_until + timedelta(microseconds=1),
    )
    assert outliving.eligible is False
    assert outliving.rejection_reasons == (LockOwnershipRejectionReason.VALIDITY_EXCEEDS_LOCK,)


def test_expired_lease_produces_a_typed_negative_assessment() -> None:
    receipt = _receipt()
    assert receipt.valid_until is not None
    expired = _assessment(
        receipt,
        evaluated_at=receipt.valid_until,
        valid_until=receipt.valid_until + timedelta(seconds=1),
    )
    assert expired.eligible is False
    assert expired.rejection_reasons == (LockOwnershipRejectionReason.EXPIRED,)


@pytest.mark.parametrize("field", ["verifier_id", "verifier_version"])
def test_live_assessment_requires_verifier_identity(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _assessment(_receipt(), **{field: " "})


def test_lock_contracts_reject_unsupported_schema_versions() -> None:
    receipt = _receipt()
    with pytest.raises(ValueError, match="unsupported resource lock receipt"):
        replace(receipt, schema_version="9.9.9")
    with pytest.raises(ValueError, match="unsupported live lock assessment"):
        replace(_assessment(receipt), schema_version="9.9.9")


def test_lock_contracts_reject_schema_string_subclasses() -> None:
    class LyingSchema(str):
        def __ne__(self, value: object) -> bool:
            return False

    with pytest.raises(ValueError, match="unsupported resource lock receipt"):
        _receipt(schema_version=LyingSchema("9.9.9"))
    with pytest.raises(ValueError, match="unsupported live lock assessment"):
        replace(_assessment(_receipt()), schema_version=LyingSchema("9.9.9"))


def test_receipt_rejects_datetime_subclasses() -> None:
    class LyingDatetime(datetime):
        pass

    lying_time = LyingDatetime(2026, 9, 10, 5, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="MUST include a timezone"):
        _receipt(acquired_at=lying_time)


def test_lock_contracts_require_explicit_no_authority() -> None:
    receipt = _receipt()
    with pytest.raises(ValueError, match="MUST NOT grant"):
        replace(receipt, execution_authority=None)
    with pytest.raises(ValueError, match="MUST NOT grant"):
        replace(_assessment(receipt), execution_authority=0)


def test_session_receipt_rejects_blank_identity() -> None:
    for identity in (" ", " session:example "):
        with pytest.raises(ValueError, match="session lifetime"):
            _receipt(
                fencing_generation=None,
                session_identity=identity,
                valid_until=None,
            )


def test_assessment_embeds_exact_validated_acquisition_receipt() -> None:
    receipt = _receipt()
    assessment = _assessment(receipt)
    assert assessment.acquisition_receipt is receipt
    with pytest.raises(ValueError, match="validated acquisition receipt"):
        replace(assessment, acquisition_receipt={"receipt_digest": receipt.receipt_digest})


def test_assessment_rejects_receipt_subclass() -> None:
    class UnvalidatedReceipt(ResourceLockAcquisitionReceipt):
        def __post_init__(self) -> None:
            pass

    receipt = _receipt()
    unvalidated = UnvalidatedReceipt(
        **{field: getattr(receipt, field) for field in receipt.__dataclass_fields__}
    )
    with pytest.raises(ValueError, match="validated acquisition receipt"):
        _assessment(unvalidated)
    with pytest.raises(TypeError, match="does not support subclasses"):
        UnvalidatedReceipt.create(**_values())


def test_assessment_factory_rejects_subclass() -> None:
    class UnvalidatedAssessment(LiveLockOwnershipAssessment):
        def __post_init__(self) -> None:
            pass

    receipt = _receipt()
    with pytest.raises(TypeError, match="does not support subclasses"):
        UnvalidatedAssessment.create(
            receipt,
            current_fencing_generation=4,
            current_session_identity=None,
            verifier_id="postgres-lock-readback",
            verifier_version="1.0.0",
            trust_anchor_id=receipt.trust_anchor_id,
            provider_attestation_digest="sha256:" + "5" * 64,
            evaluated_at=_NOW + timedelta(seconds=1),
            valid_until=_NOW + timedelta(seconds=2),
        )


def test_assessment_constructor_cannot_bypass_derived_rejections() -> None:
    assessment = _assessment(_receipt())
    with pytest.raises(ValueError, match="rejection reasons mismatched state"):
        replace(
            assessment,
            current_fencing_generation=5,
            trust_anchor_id="postgres:other",
            eligible=True,
            rejection_reasons=(),
            assessment_digest="sha256:" + "0" * 64,
        )


@pytest.mark.parametrize("attempt", [True, 1.5])
def test_receipt_rejects_non_integer_attempt(attempt: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _receipt(attempt=attempt)


def test_create_rejects_caller_assertion_of_derived_reason() -> None:
    with pytest.raises(ValueError, match="provider-observed reasons"):
        _assessment(
            _receipt(),
            rejection_reasons=(LockOwnershipRejectionReason.FENCE_MISMATCH,),
        )


def test_receipt_rejects_noncanonical_lock_key() -> None:
    with pytest.raises(ValueError, match="lock key MUST be canonical"):
        _receipt(lock_key=" fdai:resource:example ")


def test_receipt_rejects_lock_key_string_subclass() -> None:
    class NonCanonicalString(str):
        def strip(self, chars: str | None = None) -> str:
            return self

    with pytest.raises(ValueError, match="lock key MUST be non-empty"):
        _receipt(lock_key=NonCanonicalString(" fdai:resource:example "))


def test_receipt_rejects_session_string_subclass() -> None:
    class LyingSession(str):
        def __eq__(self, value: object) -> bool:
            return True

        def strip(self, chars: str | None = None) -> str:
            return str(self)

    with pytest.raises(ValueError, match="session lifetime"):
        _receipt(
            fencing_generation=None,
            session_identity=LyingSession("session:victim"),
            valid_until=None,
        )


def test_contracts_reject_digest_string_subclasses() -> None:
    class LyingDigest(str):
        def __ne__(self, value: object) -> bool:
            return False

    receipt = _receipt()
    with pytest.raises(ValueError, match="digest fields MUST be SHA-256"):
        replace(receipt, receipt_digest=LyingDigest("not-a-digest"))
    with pytest.raises(ValueError, match="digest MUST be SHA-256"):
        replace(_assessment(receipt), assessment_digest=LyingDigest("not-a-digest"))


def test_assessment_rejects_untyped_rejection_reasons() -> None:
    with pytest.raises(ValueError, match="canonical enum"):
        _assessment(_receipt(), rejection_reasons=("lock_lost",))


def test_assessment_rejects_one_shot_rejection_iterable() -> None:
    reasons = (reason for reason in (LockOwnershipRejectionReason.LOCK_LOST,))
    with pytest.raises(ValueError, match="canonical enum"):
        _assessment(_receipt(), rejection_reasons=reasons)


def test_contracts_reject_non_utc_stored_timestamps() -> None:
    receipt = _receipt()
    non_utc_acquired = receipt.acquired_at.astimezone(timezone(timedelta(hours=9)))
    with pytest.raises(ValueError, match="normalized to UTC"):
        replace(receipt, acquired_at=non_utc_acquired)

    assessment = _assessment(receipt)
    non_utc_evaluated = assessment.evaluated_at.astimezone(timezone(timedelta(hours=9)))
    with pytest.raises(ValueError, match="normalized to UTC"):
        replace(assessment, evaluated_at=non_utc_evaluated)


@pytest.mark.parametrize("generation", [True, 4.0])
def test_lock_contracts_reject_non_integer_fencing(generation: object) -> None:
    with pytest.raises(ValueError, match="lease lifetime"):
        _receipt(fencing_generation=generation)
    with pytest.raises(ValueError, match="positive integer"):
        _assessment(_receipt(), current_fencing_generation=generation)


def test_live_assessment_requires_exclusive_lifetime_form() -> None:
    lease_assessment = _assessment(
        _receipt(),
        current_session_identity="session:unexpected",
    )
    assert lease_assessment.eligible is False
    assert LockOwnershipRejectionReason.SESSION_MISMATCH in (lease_assessment.rejection_reasons)

    session_receipt = _receipt(
        fencing_generation=None,
        session_identity="session:example",
        valid_until=None,
    )
    session_assessment = _assessment(
        session_receipt,
        current_fencing_generation=1,
        current_session_identity="session:example",
    )
    assert session_assessment.eligible is False
    assert LockOwnershipRejectionReason.FENCE_MISMATCH in (session_assessment.rejection_reasons)


def test_live_assessment_rejects_noncanonical_session_identity() -> None:
    receipt = _receipt(
        fencing_generation=None,
        session_identity="session:example",
        valid_until=None,
    )
    with pytest.raises(ValueError, match="session identity MUST be canonical"):
        _assessment(
            receipt,
            current_fencing_generation=None,
            current_session_identity=" session:example ",
        )
