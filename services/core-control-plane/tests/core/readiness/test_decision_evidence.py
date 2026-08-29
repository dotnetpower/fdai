"""Decision-critical evidence readiness boundary tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.readiness.decision_evidence import (
    DecisionEvidenceReadinessGate,
    DecisionEvidenceReadinessReason,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceVerificationError,
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    LiveEvidenceClaimRequirement,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)

_NOW = datetime(2026, 8, 29, 5, 0, tzinfo=UTC)
_DIGESTS = tuple("sha256:" + char * 64 for char in "abcdef0")


def _receipt(**overrides: object) -> DecisionCriticalEvidenceReceipt:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "authority_class": "provider_observation",
        "source_identity": "principal:inventory-reader",
        "authentication_evidence_digest": _DIGESTS[0],
        "scope_digest": _DIGESTS[1],
        "purpose_id": "readiness",
        "producer_id": "inventory-observer",
        "producer_version": "1.0.0",
        "method_id": "resource-health-query",
        "method_version": "1.0.0",
        "source_revision": "api-version:2026-01-01",
        "evidence_digest": _DIGESTS[2],
        "provenance_digest": _DIGESTS[3],
        "event_at": _NOW,
        "evidence_cutoff": _NOW + timedelta(minutes=1),
        "recorded_at": _NOW + timedelta(minutes=2),
        "fresh_until": _NOW + timedelta(minutes=10),
        "freshness_policy_id": "readiness-eight-minute",
        "freshness_policy_version": "1.0.0",
        "freshness_policy_digest": _DIGESTS[4],
        "freshness_ceiling_seconds": 540,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": _DIGESTS[5],
        "conflict_status": EvidenceConflictStatus.CLEAR,
        "conflict_evidence_digest": _DIGESTS[6],
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    values.update(overrides)
    return DecisionCriticalEvidenceReceipt.model_validate(
        {
            **values,
            "receipt_digest": decision_critical_evidence_receipt_digest(**values),
        }
    )


def _requirement() -> LiveEvidenceClaimRequirement:
    return LiveEvidenceClaimRequirement(
        allowed_authority_classes=("provider_observation",),
        allowed_source_identities=("principal:inventory-reader",),
        scope_digest=_DIGESTS[1],
        purpose_id="readiness",
        producer_id="inventory-observer",
        producer_version="1.0.0",
        method_id="resource-health-query",
        method_version="1.0.0",
        source_revision="api-version:2026-01-01",
        freshness_policy_digest=_DIGESTS[4],
        freshness_ceiling_seconds=540,
        minimum_completeness_basis_points=10_000,
    )


def _bundle(receipt: DecisionCriticalEvidenceReceipt) -> DecisionEvidenceVerificationBundle:
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    proofs = tuple(
        DecisionEvidenceVerificationProof(
            kind=kind,
            receipt_digest=receipt.receipt_digest,
            subject_digest=subject,
            proof_digest="sha256:" + str(index) * 64,
            verifier_id="azure.readback",
            verifier_version="1.0.0",
            trust_anchor_id="azure:managed-identity",
            issued_at=_NOW + timedelta(minutes=2),
            valid_until=_NOW + timedelta(minutes=8),
        )
        for index, (kind, subject) in enumerate(subjects.items(), start=1)
    )
    return DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
        verified_at=_NOW + timedelta(minutes=2),
        valid_until=_NOW + timedelta(minutes=8),
        proofs=proofs,
    )


class _Verifier:
    def __init__(self, bundle: DecisionEvidenceVerificationBundle) -> None:
        self.bundle = bundle

    async def verify(self, receipt, *, trust_anchor_id):
        del receipt, trust_anchor_id
        return self.bundle


def _gate(
    receipt: DecisionCriticalEvidenceReceipt,
    *,
    bundle=None,
    verifier_id="azure.readback",
    revoked=False,
):
    selected = bundle or _bundle(receipt)
    return DecisionEvidenceReadinessGate(
        registry=DecisionEvidenceVerifierRegistry(
            (
                DecisionEvidenceVerifierBinding(
                    authority_class=receipt.authority_class,
                    method_id=receipt.method_id,
                    verifier_id=verifier_id,
                    verifier_version="1.0.0",
                    trust_anchor_id="azure:managed-identity",
                    verifier=_Verifier(selected),
                    revoked=revoked,
                ),
            )
        )
    )


async def test_matching_independent_proofs_make_evidence_eligible_only() -> None:
    receipt = _receipt()

    result = await _gate(receipt).evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )

    assert result.eligible is True
    assert result.reason is DecisionEvidenceReadinessReason.VERIFIED
    assert result.verification_bundle_digest == _bundle(receipt).bundle_digest
    assert result.admission is not None
    assert result.admission.receipt_digest == receipt.receipt_digest
    assert result.admission.evidence_digest == receipt.evidence_digest
    assert result.admission.scope_digest == receipt.scope_digest
    assert result.admission.purpose_id == receipt.purpose_id
    assert result.admission.source_revision == receipt.source_revision
    assert result.execution_authority is result.promotion_authority is False


@pytest.mark.parametrize(
    "receipt",
    [
        _receipt(synthetic=True),
        _receipt(completeness_basis_points=9_999),
        _receipt(
            conflict_status=EvidenceConflictStatus.CONFLICTING,
            conflict_evidence_digests=(_DIGESTS[0],),
        ),
    ],
)
async def test_synthetic_incomplete_or_conflicting_receipt_fails_preflight(
    receipt: DecisionCriticalEvidenceReceipt,
) -> None:
    result = await _gate(receipt).evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )

    assert result.eligible is False
    assert result.reason is DecisionEvidenceReadinessReason.PREFLIGHT_REJECTED


async def test_missing_untrusted_or_self_verifier_fails_closed() -> None:
    receipt = _receipt()
    missing = DecisionEvidenceReadinessGate(registry=DecisionEvidenceVerifierRegistry(()))
    unavailable = await missing.evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )
    self_verification = await _gate(
        receipt,
        verifier_id=receipt.producer_id,
    ).evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )
    revoked = await _gate(receipt, revoked=True).evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )

    assert unavailable.reason is DecisionEvidenceReadinessReason.VERIFIER_UNAVAILABLE
    assert unavailable.admission is None
    assert self_verification.reason is DecisionEvidenceReadinessReason.SELF_VERIFICATION
    assert self_verification.admission is None
    assert revoked.reason is DecisionEvidenceReadinessReason.UNTRUSTED_VERIFIER
    assert revoked.admission is None


async def test_forged_subject_and_expired_proof_fail_closed() -> None:
    receipt = _receipt()
    valid = _bundle(receipt)
    forged_proof = valid.proofs[0].model_copy(update={"subject_digest": "sha256:" + "9" * 64})
    forged = DecisionEvidenceVerificationBundle.create(
        receipt_digest=valid.receipt_digest,
        verifier_id=valid.verifier_id,
        verifier_version=valid.verifier_version,
        trust_anchor_id=valid.trust_anchor_id,
        verified_at=valid.verified_at,
        valid_until=valid.valid_until,
        proofs=(forged_proof, *valid.proofs[1:]),
        revoked=valid.revoked,
        execution_authority=valid.execution_authority,
    )
    forged_result = await _gate(receipt, bundle=forged).evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )
    expired_result = await _gate(receipt).evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=9),
    )

    assert forged_result.reason is DecisionEvidenceReadinessReason.PROOF_MISMATCH
    assert expired_result.reason is DecisionEvidenceReadinessReason.PROOF_NOT_CURRENT


@pytest.mark.parametrize(
    "failure",
    [
        DecisionEvidenceVerificationError("provider readback unavailable"),
        RuntimeError("managed identity unavailable"),
        OSError("provider transport unavailable"),
        LookupError("provider SDK response unavailable"),
    ],
)
async def test_expected_verifier_failure_is_a_bounded_rejection(failure: Exception) -> None:
    receipt = _receipt()

    class _FailingVerifier:
        async def verify(self, receipt, *, trust_anchor_id):
            del receipt, trust_anchor_id
            raise failure

    registry = DecisionEvidenceVerifierRegistry(
        (
            DecisionEvidenceVerifierBinding(
                authority_class=receipt.authority_class,
                method_id=receipt.method_id,
                verifier_id="azure.readback",
                verifier_version="1.0.0",
                trust_anchor_id="azure:managed-identity",
                verifier=_FailingVerifier(),
            ),
        )
    )

    result = await DecisionEvidenceReadinessGate(registry=registry).evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )

    assert result.reason is DecisionEvidenceReadinessReason.VERIFIER_FAILED


async def test_verifier_cancellation_is_not_converted_to_rejection() -> None:
    receipt = _receipt()

    class _CancelledVerifier:
        async def verify(self, receipt, *, trust_anchor_id):
            del receipt, trust_anchor_id
            raise asyncio.CancelledError

    registry = DecisionEvidenceVerifierRegistry(
        (
            DecisionEvidenceVerifierBinding(
                authority_class=receipt.authority_class,
                method_id=receipt.method_id,
                verifier_id="azure.readback",
                verifier_version="1.0.0",
                trust_anchor_id="azure:managed-identity",
                verifier=_CancelledVerifier(),
            ),
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await DecisionEvidenceReadinessGate(registry=registry).evaluate(
            receipt,
            _requirement(),
            evaluated_at=_NOW + timedelta(minutes=3),
        )
