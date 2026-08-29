"""Provider-neutral decision-evidence verifier and registry seams."""

from __future__ import annotations

import re
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
)


class DecisionEvidenceVerificationError(RuntimeError):
    """Expected bounded failure reported by a verifier implementation."""


_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class DecisionEvidenceAdmissionRejectionReason(StrEnum):
    """Why independently verified evidence cannot enter a decision boundary."""

    EVIDENCE_MISMATCH = "evidence_mismatch"
    NOT_CURRENT = "not_current"
    PURPOSE_MISMATCH = "purpose_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    SOURCE_REVISION_MISMATCH = "source_revision_mismatch"


@dataclass(frozen=True, slots=True)
class DecisionEvidenceAdmission:
    """Short-lived evidence eligibility emitted by the trusted readiness gate."""

    receipt_digest: str
    verification_bundle_digest: str
    evidence_digest: str
    scope_digest: str
    purpose_id: str
    source_revision: str
    verified_at: datetime
    valid_until: datetime
    execution_authority: bool = False
    promotion_authority: bool = False

    def __post_init__(self) -> None:
        for field_name, value in (
            ("receipt_digest", self.receipt_digest),
            ("verification_bundle_digest", self.verification_bundle_digest),
            ("evidence_digest", self.evidence_digest),
            ("scope_digest", self.scope_digest),
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError(f"decision evidence admission {field_name} MUST be SHA-256")
        for field_name, value in (
            ("purpose_id", self.purpose_id),
            ("source_revision", self.source_revision),
        ):
            if not value.strip() or len(value) > 512:
                raise ValueError(
                    f"decision evidence admission {field_name} MUST be bounded non-empty text"
                )
        if (
            self.verified_at.tzinfo is None
            or self.verified_at.utcoffset() is None
            or self.valid_until.tzinfo is None
            or self.valid_until.utcoffset() is None
        ):
            raise ValueError("decision evidence admission times MUST be timezone-aware")
        if self.valid_until <= self.verified_at:
            raise ValueError("decision evidence admission expiry MUST follow verification")
        if (
            type(self.execution_authority) is not bool
            or type(self.promotion_authority) is not bool
            or self.execution_authority
            or self.promotion_authority
        ):
            raise ValueError("decision evidence admission MUST NOT grant authority")
        object.__setattr__(self, "verified_at", self.verified_at.astimezone(UTC))
        object.__setattr__(self, "valid_until", self.valid_until.astimezone(UTC))

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical admission fields retained by downstream evidence."""

        return {
            "evidence_digest": self.evidence_digest,
            "execution_authority": False,
            "promotion_authority": False,
            "purpose_id": self.purpose_id,
            "receipt_digest": self.receipt_digest,
            "scope_digest": self.scope_digest,
            "source_revision": self.source_revision,
            "valid_until": self.valid_until.isoformat(),
            "verification_bundle_digest": self.verification_bundle_digest,
            "verified_at": self.verified_at.isoformat(),
        }


def assess_decision_evidence_admission(
    admission: DecisionEvidenceAdmission,
    *,
    expected_evidence_digest: str,
    expected_scope_digest: str,
    expected_purpose_id: str,
    expected_source_revision: str,
    evaluated_at: datetime,
) -> tuple[DecisionEvidenceAdmissionRejectionReason, ...]:
    """Recheck an admission against one exact decision input and evaluation time."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("decision evidence admission evaluation time MUST be timezone-aware")
    normalized_at = evaluated_at.astimezone(UTC)
    reasons: list[DecisionEvidenceAdmissionRejectionReason] = []
    if admission.evidence_digest != expected_evidence_digest:
        reasons.append(DecisionEvidenceAdmissionRejectionReason.EVIDENCE_MISMATCH)
    if not admission.verified_at <= normalized_at <= admission.valid_until:
        reasons.append(DecisionEvidenceAdmissionRejectionReason.NOT_CURRENT)
    if admission.purpose_id != expected_purpose_id:
        reasons.append(DecisionEvidenceAdmissionRejectionReason.PURPOSE_MISMATCH)
    if admission.scope_digest != expected_scope_digest:
        reasons.append(DecisionEvidenceAdmissionRejectionReason.SCOPE_MISMATCH)
    if admission.source_revision != expected_source_revision:
        reasons.append(DecisionEvidenceAdmissionRejectionReason.SOURCE_REVISION_MISMATCH)
    return tuple(sorted(reasons, key=str))


class DecisionEvidenceVerifier(Protocol):
    """Return five independent proofs for one exact evidence receipt."""

    def verify(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        *,
        trust_anchor_id: str,
    ) -> Awaitable[DecisionEvidenceVerificationBundle]: ...


class DecisionEvidenceAdmissionProvider(Protocol):
    """Return a trusted admission for one exact decision input or no admission."""

    def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> Awaitable[DecisionEvidenceAdmission | None]: ...


@dataclass(frozen=True, slots=True)
class DecisionEvidenceVerifierBinding:
    """Governed mapping from one evidence class and method to a verifier."""

    authority_class: str
    method_id: str
    verifier_id: str
    verifier_version: str
    trust_anchor_id: str
    verifier: DecisionEvidenceVerifier
    valid_from: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=UTC))
    valid_until: datetime = field(default_factory=lambda: datetime.max.replace(tzinfo=UTC))
    revoked: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("authority_class", self.authority_class),
            ("method_id", self.method_id),
            ("verifier_id", self.verifier_id),
            ("verifier_version", self.verifier_version),
            ("trust_anchor_id", self.trust_anchor_id),
        ):
            if not value.strip() or len(value) > 512:
                raise ValueError(
                    f"DecisionEvidenceVerifierBinding.{name} MUST be bounded non-empty text"
                )
        if self.valid_from.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("decision evidence verifier binding times MUST be timezone-aware")
        if self.valid_until <= self.valid_from:
            raise ValueError("decision evidence verifier binding expiry MUST follow activation")
        if not isinstance(self.revoked, bool):
            raise ValueError("decision evidence verifier binding revoked MUST be a boolean")

    def active_at(self, evaluated_at: datetime) -> bool:
        """Return whether the reviewed trust binding is current and not revoked."""

        if evaluated_at.tzinfo is None:
            raise ValueError("decision evidence verifier evaluation time MUST be timezone-aware")
        return not self.revoked and self.valid_from <= evaluated_at <= self.valid_until


class DecisionEvidenceVerifierRegistry:
    """Select reviewed verifier bindings without validating evidence itself."""

    def __init__(self, bindings: tuple[DecisionEvidenceVerifierBinding, ...]) -> None:
        indexed: dict[tuple[str, str], DecisionEvidenceVerifierBinding] = {}
        for binding in bindings:
            key = (binding.authority_class, binding.method_id)
            if key in indexed:
                raise ValueError("decision evidence verifier binding is duplicated")
            indexed[key] = binding
        self._bindings = indexed

    def resolve(
        self,
        *,
        authority_class: str,
        method_id: str,
    ) -> DecisionEvidenceVerifierBinding | None:
        """Return the exact reviewed binding or no verifier."""

        return self._bindings.get((authority_class, method_id))


__all__ = [
    "DecisionEvidenceAdmission",
    "DecisionEvidenceAdmissionProvider",
    "DecisionEvidenceAdmissionRejectionReason",
    "DecisionEvidenceVerificationError",
    "DecisionEvidenceVerifier",
    "DecisionEvidenceVerifierBinding",
    "DecisionEvidenceVerifierRegistry",
    "assess_decision_evidence_admission",
]
