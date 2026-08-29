"""Independent decision-evidence proof contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    EvidenceVerificationProofKind,
    expected_verification_subjects,
)
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from pydantic import ValidationError

_NOW = datetime(2026, 8, 29, 5, 0, tzinfo=UTC)
_RECEIPT = "sha256:" + "a" * 64


def _proof(
    kind: EvidenceVerificationProofKind,
    subject: str,
    *,
    verifier_id: str = "azure.readback",
) -> DecisionEvidenceVerificationProof:
    return DecisionEvidenceVerificationProof(
        kind=kind,
        receipt_digest=_RECEIPT,
        subject_digest=subject,
        proof_digest="sha256:" + kind.value[0] * 64,
        verifier_id=verifier_id,
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
        issued_at=_NOW,
        valid_until=_NOW + timedelta(minutes=5),
    )


def _proofs() -> tuple[DecisionEvidenceVerificationProof, ...]:
    subjects = expected_verification_subjects(
        authentication_evidence_digest="sha256:" + "1" * 64,
        evidence_digest="sha256:" + "2" * 64,
        completeness_evidence_digest="sha256:" + "3" * 64,
        conflict_evidence_digest="sha256:" + "4" * 64,
        freshness_policy_digest="sha256:" + "5" * 64,
    )
    return tuple(_proof(kind, subject) for kind, subject in subjects.items())


def test_bundle_canonicalizes_all_five_proof_classes() -> None:
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=_RECEIPT,
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
        verified_at=_NOW,
        valid_until=_NOW + timedelta(minutes=5),
        proofs=tuple(reversed(_proofs())),
    )

    assert tuple(proof.kind for proof in bundle.proofs) == tuple(
        sorted(EvidenceVerificationProofKind, key=str)
    )
    assert bundle.execution_authority is False
    assert len(bundle.bundle_digest) == 71
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "decision-evidence-verification",
        bundle.model_dump(mode="json"),
    )


def test_bundle_rejects_missing_or_mismatched_proofs() -> None:
    with pytest.raises(ValidationError, match="at least 5 items"):
        DecisionEvidenceVerificationBundle.create(
            receipt_digest=_RECEIPT,
            verifier_id="azure.readback",
            verifier_version="1.0.0",
            trust_anchor_id="azure:managed-identity",
            verified_at=_NOW,
            valid_until=_NOW + timedelta(minutes=5),
            proofs=_proofs()[:-1],
        )
    mismatched = (
        *_proofs()[:-1],
        _proof(EvidenceVerificationProofKind.EVIDENCE, "sha256:" + "9" * 64),
    )
    with pytest.raises(ValidationError, match="five ordered proof classes"):
        DecisionEvidenceVerificationBundle.create(
            receipt_digest=_RECEIPT,
            verifier_id="azure.readback",
            verifier_version="1.0.0",
            trust_anchor_id="azure:managed-identity",
            verified_at=_NOW,
            valid_until=_NOW + timedelta(minutes=5),
            proofs=mismatched,
        )


def test_bundle_rejects_tampered_digest() -> None:
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=_RECEIPT,
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
        verified_at=_NOW,
        valid_until=_NOW + timedelta(minutes=5),
        proofs=_proofs(),
    )

    with pytest.raises(ValidationError, match="digest mismatched"):
        DecisionEvidenceVerificationBundle.model_validate(
            {**bundle.model_dump(mode="json"), "bundle_digest": "sha256:" + "0" * 64}
        )
