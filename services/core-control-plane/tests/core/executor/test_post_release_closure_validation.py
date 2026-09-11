"""Rejection contract for the durable post-release closure record.

The closure record is the only durable proof that a real dispatch ended: it
binds the lock release, the terminal evidence, the reservation, and the target
generation into one revision. Every tampered field below MUST fail closed -
a closure that can be edited after the fact is not evidence at all.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.executor.idempotency_reservation import ReservationState
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureIdentity,
    PostReleaseClosurePhase,
    PostReleaseClosureRecord,
    PostReleaseContinuityState,
    PostReleaseReconciliationEvidence,
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import AuthoritativeSinkState
from fdai.core.executor.target_dispatch_fence import TargetDispatchFenceState
from fdai.shared.providers.resource_lock import ResourceLockReleaseState

from tests.core.executor.test_post_release_closure import (
    _initial_plan,
    _reconciliation_evidence,
)
from tests.core.executor.test_safeguard_dispatch_checkpoint import (
    _NOW,
    _dispatch_started_record,
    _evidence_fixture,
)

_WRONG_DIGEST = "sha256:" + "9" * 64


def _resolved_record() -> PostReleaseClosureRecord:
    return _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED).record


def _quarantined_record() -> PostReleaseClosureRecord:
    return _initial_plan(sink_state=AuthoritativeSinkState.UNKNOWN).record


def _evidence() -> PostReleaseReconciliationEvidence:
    return _reconciliation_evidence(
        _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED),
        kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
        outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
    )


class TestReconciliationEvidence:
    def test_an_unsupported_schema_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported post-release reconciliation"):
            replace(_evidence(), schema_version="2.0.0")

    @pytest.mark.parametrize(
        "field",
        ["synthetic", "execution_authority", "effect_verification_authority"],
    )
    def test_reconciliation_evidence_can_never_carry_authority(self, field: str) -> None:
        with pytest.raises(ValueError, match="MUST NOT grant authority"):
            replace(_evidence(), **{field: True})

    def test_a_non_enum_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="evidence kind is invalid"):
            replace(_evidence(), kind="authoritative_sink_status")

    def test_a_non_enum_outcome_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="reconciliation outcome is invalid"):
            replace(_evidence(), outcome="sink_committed")

    def test_a_sink_outcome_requires_authoritative_sink_evidence(self) -> None:
        with pytest.raises(ValueError, match="authority mismatched outcome"):
            replace(
                _evidence(),
                kind=ReconciliationEvidenceKind.INDEPENDENT_EFFECT,
            )

    def test_a_non_positive_generation_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="reconciliation generation MUST be positive"):
            replace(_evidence(), target_fence_generation=0)

    def test_persistence_cannot_predate_observation(self) -> None:
        evidence = _evidence()

        with pytest.raises(ValueError, match="persistence predates observation"):
            replace(evidence, persisted_at=evidence.observed_at - timedelta(seconds=1))

    def test_a_subclass_cannot_be_created(self) -> None:
        class _Forged(PostReleaseReconciliationEvidence):
            pass

        evidence = _evidence()

        with pytest.raises(TypeError, match="does not support subclasses"):
            _Forged.create(
                kind=evidence.kind,
                outcome=evidence.outcome,
                target_digest=evidence.target_digest,
                target_fence_generation=evidence.target_fence_generation,
                evidence_identity_digest=evidence.evidence_identity_digest,
                source_id=evidence.source_id,
                source_version=evidence.source_version,
                trust_anchor_id=evidence.trust_anchor_id,
                evidence_digest=evidence.evidence_digest,
                observed_at=evidence.observed_at,
                persisted_at=evidence.persisted_at,
                append_receipt_digest=evidence.append_receipt_digest,
            )


class TestClosureIdentity:
    def test_an_unsupported_schema_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported post-release closure identity"):
            replace(_resolved_record().identity, schema_version="2.0.0")

    @pytest.mark.parametrize(
        "field",
        ["execution_authority", "effect_verification_authority"],
    )
    def test_a_closure_identity_can_never_carry_authority(self, field: str) -> None:
        with pytest.raises(ValueError, match="MUST NOT grant authority"):
            replace(_resolved_record().identity, **{field: True})

    def test_a_non_positive_reservation_attempt_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="reservation attempt MUST be positive"):
            replace(_resolved_record().identity, reservation_attempt=0)

    def test_a_non_positive_target_generation_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="target generation MUST be positive"):
            replace(_resolved_record().identity, target_fence_generation=0)

    def test_a_closure_key_must_bind_its_reservation_attempt(self) -> None:
        with pytest.raises(ValueError, match="closure key mismatched reservation attempt"):
            replace(_resolved_record().identity, closure_key=_WRONG_DIGEST)

    def test_a_tampered_identity_digest_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="closure identity digest mismatched"):
            replace(_resolved_record().identity, identity_digest=_WRONG_DIGEST)

    def test_closure_identity_requires_pre_release_evidence(self) -> None:
        bundle, _reservation, _preparing, prepared, context = _evidence_fixture()
        started, _persistence = _dispatch_started_record(
            bundle,
            prepared_fence=prepared,
            context=context,
        )

        # The dispatch-start record is real evidence, but it precedes the
        # pre-release ownership checkpoint that closure identity depends on.
        with pytest.raises(ValueError, match="requires pre-release evidence"):
            PostReleaseClosureIdentity.from_pre_release(started)


class TestClosureRecord:
    def test_an_unsupported_schema_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported post-release closure record"):
            replace(_resolved_record(), schema_version="2.0.0")

    @pytest.mark.parametrize("field", ["execution_authority", "effect_verified"])
    def test_a_closure_record_can_never_carry_authority(self, field: str) -> None:
        with pytest.raises(ValueError, match="MUST NOT grant authority"):
            replace(_resolved_record(), **{field: True})

    def test_a_foreign_identity_object_is_rejected(self) -> None:
        class _Forged(PostReleaseClosureIdentity):
            pass

        record = _resolved_record()
        identity = record.identity
        forged = _Forged(**{field: getattr(identity, field) for field in identity.__slots__})

        with pytest.raises(ValueError, match="requires exact identity"):
            replace(record, identity=forged)

    def test_a_non_positive_revision_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="closure revision MUST be positive"):
            replace(_resolved_record(), revision=0)

    def test_an_initial_closure_cannot_claim_a_predecessor(self) -> None:
        with pytest.raises(ValueError, match="initial post-release closure predecessor"):
            replace(_resolved_record(), prior_record_digest=_WRONG_DIGEST)

    def test_a_later_revision_requires_a_reconciliation_predecessor(self) -> None:
        with pytest.raises(ValueError, match="reconciled post-release closure predecessor"):
            replace(_resolved_record(), revision=2)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("outcome", "resolved", "closure outcome is invalid"),
            ("continuity_state", "continuity", "continuity state is invalid"),
            ("reservation_state", "terminal", "reservation state is invalid"),
            ("fence_state", "resolved", "fence state is invalid"),
            ("release_state", "released", "release state is invalid"),
        ],
    )
    def test_a_raw_string_never_substitutes_for_a_state_enum(
        self,
        field: str,
        value: str,
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            replace(_resolved_record(), **{field: value})

    @pytest.mark.parametrize(
        "field",
        ["pre_release_record_revision", "reservation_revision", "fence_revision"],
    )
    def test_a_non_positive_bound_revision_is_rejected(self, field: str) -> None:
        with pytest.raises(ValueError, match=f"post-release {field} MUST be positive"):
            replace(_resolved_record(), **{field: 0})

    def test_a_closure_cannot_close_before_the_release_was_recorded(self) -> None:
        record = _resolved_record()

        with pytest.raises(ValueError, match="closure chronology is invalid"):
            replace(record, closed_at=record.release_recorded_at - timedelta(seconds=1))

    def test_an_observation_cannot_postdate_its_own_recording(self) -> None:
        record = _resolved_record()

        with pytest.raises(ValueError, match="closure chronology is invalid"):
            replace(
                record,
                release_observed_at=record.release_recorded_at + timedelta(seconds=1),
            )

    def test_a_known_release_state_requires_an_observation(self) -> None:
        with pytest.raises(ValueError, match="known post-release release state requires"):
            replace(_resolved_record(), release_observed_at=None)

    def test_a_closure_cannot_claim_independent_effect_verification(self) -> None:
        with pytest.raises(ValueError, match="cannot claim independent effect verification"):
            replace(_resolved_record(), independent_effect_state="verified")

    def test_a_tampered_audit_digest_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="audit closure digest mismatched"):
            replace(_resolved_record(), audit_closure_digest=_WRONG_DIGEST)

    def test_a_tampered_outbox_identity_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="outbox identity mismatched"):
            replace(_resolved_record(), outbox_event_id=_WRONG_DIGEST)

    def test_a_tampered_record_digest_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="closure record digest mismatched"):
            replace(_resolved_record(), record_digest=_WRONG_DIGEST)


class TestClosureShape:
    def test_a_resolved_outcome_requires_a_resolved_target_generation(self) -> None:
        with pytest.raises(ValueError, match="outcome mismatched target fence"):
            replace(_resolved_record(), fence_state=TargetDispatchFenceState.QUARANTINED)

    def test_a_resolved_closure_requires_a_terminal_reservation(self) -> None:
        with pytest.raises(ValueError, match="requires terminal reservation"):
            replace(_resolved_record(), reservation_state=ReservationState.OUTCOME_UNKNOWN)

    def test_a_quarantined_closure_requires_an_unknown_reservation(self) -> None:
        with pytest.raises(ValueError, match="quarantined closure requires unknown reservation"):
            replace(_quarantined_record(), reservation_state=ReservationState.TERMINAL)

    def test_an_initial_closure_cannot_carry_reconciliation_evidence(self) -> None:
        with pytest.raises(ValueError, match="cannot contain reconciliation evidence"):
            replace(_resolved_record(), reconciliation_evidence=_evidence())

    def test_an_initial_resolved_closure_requires_proven_continuity(self) -> None:
        with pytest.raises(ValueError, match="initial resolved closure requires proven continuity"):
            replace(
                _resolved_record(),
                continuity_state=PostReleaseContinuityState.CONTINUITY_UNPROVEN,
            )

    def test_a_reconciliation_phase_requires_evidence_and_a_resolved_outcome(self) -> None:
        record = _resolved_record()
        overrides: dict[str, Any] = {
            "revision": 2,
            "prior_record_digest": record.record_digest,
            "phase": PostReleaseClosurePhase.RECONCILIATION,
            "closed_at": record.closed_at + timedelta(seconds=1),
        }

        with pytest.raises(ValueError, match="reconciliation requires evidence"):
            replace(record, **overrides)


def test_the_closure_fixtures_stay_chronologically_sound() -> None:
    record = _resolved_record()

    assert record.closed_at >= record.release_recorded_at
    assert record.closed_at == _NOW + timedelta(seconds=4)
    assert record.phase is PostReleaseClosurePhase.INITIAL
    assert record.revision == 1
    assert record.release_state is ResourceLockReleaseState.RELEASED
