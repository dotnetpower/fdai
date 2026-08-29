"""Azure Managed Identity and provider-readback decision evidence verifier."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
)

from fdai.shared.providers.workload_identity import WorkloadIdentity


class AzureManagedIdentityAttestationReader(Protocol):
    """Verify source identity and authentication through an Azure trust anchor."""

    async def attest(
        self,
        *,
        token: str,
        receipt: DecisionCriticalEvidenceReceipt,
        trust_anchor_id: str,
    ) -> DecisionEvidenceVerificationProof: ...


class AzureProviderEvidenceReadbackReader(Protocol):
    """Independently read back evidence, completeness, conflict, and policy proofs."""

    async def readback(
        self,
        *,
        token: str,
        receipt: DecisionCriticalEvidenceReceipt,
        trust_anchor_id: str,
    ) -> tuple[DecisionEvidenceVerificationProof, ...]: ...


class AzureManagedIdentityDecisionEvidenceVerifier:
    """Build a proof bundle without exposing or retaining the managed identity token."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        attestation_reader: AzureManagedIdentityAttestationReader,
        readback_reader: AzureProviderEvidenceReadbackReader,
        verifier_id: str,
        verifier_version: str,
        audience: str = "https://management.azure.com/.default",
        timeout_seconds: float = 10.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not verifier_id.strip() or not verifier_version.strip() or not audience.strip():
            raise ValueError("Azure decision evidence verifier identity fields MUST be non-empty")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Azure decision evidence verifier timeout MUST be in (0, 30]")
        self._identity = identity
        self._attestation_reader = attestation_reader
        self._readback_reader = readback_reader
        self._verifier_id = verifier_id
        self._verifier_version = verifier_version
        self._audience = audience
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def verify(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        *,
        trust_anchor_id: str,
    ) -> DecisionEvidenceVerificationBundle:
        """Obtain short-lived identity and independent provider readback proofs."""

        async with asyncio.timeout(self._timeout_seconds):
            token = await self._identity.get_token(self._audience)
            now = self._clock()
            if now.tzinfo is None:
                raise ValueError("Azure verifier clock MUST be timezone-aware")
            if token.expires_at.tzinfo is None or token.expires_at.utcoffset() is None:
                raise ValueError("Azure verifier token expiry MUST be timezone-aware")
            if token.audience != self._audience or token.expires_at <= now:
                raise ValueError("Azure verifier received an invalid managed identity token")
            authentication = await self._attestation_reader.attest(
                token=token.token,
                receipt=receipt,
                trust_anchor_id=trust_anchor_id,
            )
            readback = await self._readback_reader.readback(
                token=token.token,
                receipt=receipt,
                trust_anchor_id=trust_anchor_id,
            )
        proofs = (authentication, *readback)
        verified_at = max(proof.issued_at for proof in proofs)
        valid_until = min(proof.valid_until for proof in proofs)
        return DecisionEvidenceVerificationBundle.create(
            receipt_digest=receipt.receipt_digest,
            verifier_id=self._verifier_id,
            verifier_version=self._verifier_version,
            trust_anchor_id=trust_anchor_id,
            verified_at=verified_at,
            valid_until=valid_until,
            proofs=proofs,
            revoked=False,
            execution_authority=False,
        )


__all__ = [
    "AzureManagedIdentityAttestationReader",
    "AzureManagedIdentityDecisionEvidenceVerifier",
    "AzureProviderEvidenceReadbackReader",
]
