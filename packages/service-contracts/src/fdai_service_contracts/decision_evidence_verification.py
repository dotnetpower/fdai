"""Versioned proofs for independent decision-evidence verification."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.executor_models import ContractBase, Digest, SemVer
from fdai_service_contracts.ontology_query import content_digest

VerifierId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]{0,127}$"),
]
TrustAnchorId = Annotated[
    str,
    Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}$"),
]


class EvidenceVerificationProofKind(StrEnum):
    """Independent proof classes required for decision eligibility."""

    AUTHENTICATION = "authentication"
    COMPLETENESS = "completeness"
    CONFLICT = "conflict"
    EVIDENCE = "evidence"
    FRESHNESS_POLICY = "freshness_policy"


_REQUIRED_PROOF_KINDS = tuple(sorted(EvidenceVerificationProofKind, key=str))


class DecisionEvidenceVerificationProof(ContractBase):
    """One content-free proof issued by an independent verifier."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: EvidenceVerificationProofKind
    receipt_digest: Digest
    subject_digest: Digest
    proof_digest: Digest
    verifier_id: VerifierId
    verifier_version: SemVer
    trust_anchor_id: TrustAnchorId
    issued_at: datetime
    valid_until: datetime
    revoked: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("issued_at", "valid_until")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision evidence proof time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _window_is_valid(self) -> DecisionEvidenceVerificationProof:
        if self.valid_until <= self.issued_at:
            raise ValueError("decision evidence proof expiry MUST follow issuance")
        return self


class _DecisionEvidenceVerificationBundleBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    receipt_digest: Digest
    verifier_id: VerifierId
    verifier_version: SemVer
    trust_anchor_id: TrustAnchorId
    verified_at: datetime
    valid_until: datetime
    proofs: Annotated[
        tuple[DecisionEvidenceVerificationProof, ...],
        Field(min_length=5, max_length=5),
    ]
    revoked: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("verified_at", "valid_until")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision evidence verification time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _proofs_match_bundle(self) -> _DecisionEvidenceVerificationBundleBody:
        if self.valid_until <= self.verified_at:
            raise ValueError("decision evidence verification expiry MUST follow verification")
        kinds = tuple(proof.kind for proof in self.proofs)
        if kinds != _REQUIRED_PROOF_KINDS:
            raise ValueError("decision evidence verification requires five ordered proof classes")
        for proof in self.proofs:
            if (
                proof.receipt_digest != self.receipt_digest
                or proof.verifier_id != self.verifier_id
                or proof.verifier_version != self.verifier_version
                or proof.trust_anchor_id != self.trust_anchor_id
                or proof.issued_at > self.verified_at
                or proof.valid_until < self.valid_until
            ):
                raise ValueError("decision evidence proof does not match its verification bundle")
        return self


class DecisionEvidenceVerificationBundle(_DecisionEvidenceVerificationBundleBody):
    """Complete independent proof bundle that grants evidence eligibility only."""

    bundle_digest: Digest

    @model_validator(mode="after")
    def _digest_matches(self) -> DecisionEvidenceVerificationBundle:
        expected = content_digest(self.model_dump(mode="json", exclude={"bundle_digest"}))
        if self.bundle_digest != expected:
            raise ValueError("decision evidence verification bundle digest mismatched")
        return self

    @classmethod
    def create(
        cls,
        *,
        receipt_digest: str,
        verifier_id: str,
        verifier_version: str,
        trust_anchor_id: str,
        verified_at: datetime,
        valid_until: datetime,
        proofs: tuple[DecisionEvidenceVerificationProof, ...],
        revoked: bool = False,
        execution_authority: bool = False,
    ) -> Self:
        """Create a canonical content-addressed bundle from five proofs."""

        body = _DecisionEvidenceVerificationBundleBody.model_validate(
            {
                "receipt_digest": receipt_digest,
                "verifier_id": verifier_id,
                "verifier_version": verifier_version,
                "trust_anchor_id": trust_anchor_id,
                "verified_at": verified_at,
                "valid_until": valid_until,
                "proofs": tuple(sorted(proofs, key=lambda proof: proof.kind.value)),
                "revoked": revoked,
                "execution_authority": execution_authority,
            }
        )
        payload = body.model_dump(mode="json")
        return cls.model_validate(
            {
                **payload,
                "bundle_digest": content_digest(payload),
            }
        )


def expected_verification_subjects(
    *,
    authentication_evidence_digest: str,
    evidence_digest: str,
    completeness_evidence_digest: str,
    conflict_evidence_digest: str,
    freshness_policy_digest: str,
) -> dict[EvidenceVerificationProofKind, str]:
    """Return the receipt fields each independent proof must verify."""

    return {
        EvidenceVerificationProofKind.AUTHENTICATION: authentication_evidence_digest,
        EvidenceVerificationProofKind.COMPLETENESS: completeness_evidence_digest,
        EvidenceVerificationProofKind.CONFLICT: conflict_evidence_digest,
        EvidenceVerificationProofKind.EVIDENCE: evidence_digest,
        EvidenceVerificationProofKind.FRESHNESS_POLICY: freshness_policy_digest,
    }


__all__ = [
    "DecisionEvidenceVerificationBundle",
    "DecisionEvidenceVerificationProof",
    "EvidenceVerificationProofKind",
    "TrustAnchorId",
    "VerifierId",
    "expected_verification_subjects",
]
