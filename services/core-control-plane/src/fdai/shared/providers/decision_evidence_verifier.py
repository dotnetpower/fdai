"""Provider-neutral decision-evidence verifier and registry seams."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
)


class DecisionEvidenceVerificationError(RuntimeError):
    """Expected bounded failure reported by a verifier implementation."""


class DecisionEvidenceVerifier(Protocol):
    """Return five independent proofs for one exact evidence receipt."""

    def verify(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        *,
        trust_anchor_id: str,
    ) -> Awaitable[DecisionEvidenceVerificationBundle]: ...


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
    "DecisionEvidenceVerificationError",
    "DecisionEvidenceVerifier",
    "DecisionEvidenceVerifierBinding",
    "DecisionEvidenceVerifierRegistry",
]
