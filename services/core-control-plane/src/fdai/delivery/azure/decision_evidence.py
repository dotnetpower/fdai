"""Azure Managed Identity and provider-readback decision evidence verifier."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx
from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    EvidenceVerificationProofKind,
    expected_verification_subjects,
)

from fdai.delivery.persistence.state_store_decision_evidence import (
    DecisionEvidenceAdmissionRecordError,
    decision_evidence_lookup_digest,
    parse_decision_evidence_record,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    resolve_current_decision_evidence_admission,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_STORAGE_AUDIENCE = "https://storage.azure.com/"
_STORAGE_API_VERSION = "2025-05-05"
_PROOF_PATH_PREFIX = "decision-evidence/v1/"
_MAX_PROOF_BYTES = 256 * 1024
_LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True, slots=True)
class AzureBlobDecisionEvidenceProofConfig:
    """Private Blob container holding independently produced proof records."""

    container_url: str
    request_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.container_url)
        segments = tuple(segment for segment in parsed.path.split("/") if segment)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(segments) != 1
        ):
            raise ValueError(
                "decision evidence proof container URL MUST identify one HTTPS container"
            )
        if (
            type(self.request_timeout_seconds) is bool
            or not math.isfinite(self.request_timeout_seconds)
            or not 0 < self.request_timeout_seconds <= 30
        ):
            raise ValueError("decision evidence proof timeout MUST be in (0, 30]")


class _AzureBlobDecisionEvidenceProofSource:
    def __init__(
        self,
        *,
        config: AzureBlobDecisionEvidenceProofConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._container_url = config.container_url.rstrip("/")
        self._timeout = config.request_timeout_seconds
        self._http = http_client

    async def read(self, *, token: str, path: str) -> object:
        response = await self._request(token=token, path=path)
        if response.status_code == 404:
            raise LookupError("decision evidence proof record is unavailable")
        if response.status_code != 200:
            raise RuntimeError(
                f"decision evidence proof storage returned HTTP {response.status_code}"
            )
        content = bytes(response.content)
        if not content or len(content) > _MAX_PROOF_BYTES:
            raise ValueError("decision evidence proof record size is outside its bound")
        expected_digest = response.headers.get("x-ms-meta-fdaisha256", "")
        if (
            len(expected_digest) != 64
            or any(character not in "0123456789abcdef" for character in expected_digest)
            or hashlib.sha256(content).hexdigest() != expected_digest
        ):
            raise ValueError("decision evidence proof record digest mismatched")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("decision evidence proof record is not valid JSON") from exc

    async def _request(self, *, token: str, path: str) -> httpx.Response:
        segments = path.split("/")
        if (
            not path.startswith(_PROOF_PATH_PREFIX)
            or "%" in path
            or "\\" in path
            or any(not segment or segment in {".", ".."} for segment in segments)
        ):
            raise ValueError("decision evidence proof path is unsafe")
        encoded = "/".join(quote(segment, safe="-._") for segment in segments)
        try:
            return await self._http.get(
                f"{self._container_url}/{encoded}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
                    "x-ms-version": _STORAGE_API_VERSION,
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("decision evidence proof storage request failed") from exc


class AzureBlobManagedIdentityAttestationReader:
    """Read one immutable authentication proof using a short-lived identity token."""

    def __init__(
        self,
        *,
        config: AzureBlobDecisionEvidenceProofConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._source = _AzureBlobDecisionEvidenceProofSource(
            config=config,
            http_client=http_client,
        )

    async def attest(
        self,
        *,
        token: str,
        receipt: DecisionCriticalEvidenceReceipt,
        trust_anchor_id: str,
    ) -> DecisionEvidenceVerificationProof:
        raw = await self._source.read(
            token=token,
            path=_proof_path("authentication", receipt.receipt_digest),
        )
        proof = DecisionEvidenceVerificationProof.model_validate(raw)
        if (
            proof.kind is not EvidenceVerificationProofKind.AUTHENTICATION
            or proof.receipt_digest != receipt.receipt_digest
            or proof.subject_digest != receipt.authentication_evidence_digest
            or proof.trust_anchor_id != trust_anchor_id
        ):
            raise ValueError("decision evidence authentication proof mismatched")
        return proof


class AzureBlobProviderEvidenceReadbackReader:
    """Read four immutable provider-readback proofs from private Blob storage."""

    def __init__(
        self,
        *,
        config: AzureBlobDecisionEvidenceProofConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._source = _AzureBlobDecisionEvidenceProofSource(
            config=config,
            http_client=http_client,
        )

    async def readback(
        self,
        *,
        token: str,
        receipt: DecisionCriticalEvidenceReceipt,
        trust_anchor_id: str,
    ) -> tuple[DecisionEvidenceVerificationProof, ...]:
        raw = await self._source.read(
            token=token,
            path=_proof_path("readback", receipt.receipt_digest),
        )
        if not isinstance(raw, dict) or set(raw) != {"proofs"}:
            raise ValueError("decision evidence readback proof record shape is invalid")
        proof_rows = raw["proofs"]
        if not isinstance(proof_rows, list):
            raise ValueError("decision evidence readback proofs MUST be an array")
        proofs = tuple(
            DecisionEvidenceVerificationProof.model_validate(item) for item in proof_rows
        )
        expected = expected_verification_subjects(
            authentication_evidence_digest=receipt.authentication_evidence_digest,
            evidence_digest=receipt.evidence_digest,
            completeness_evidence_digest=receipt.completeness_evidence_digest,
            conflict_evidence_digest=receipt.conflict_evidence_digest,
            freshness_policy_digest=receipt.freshness_policy_digest,
        )
        actual = {proof.kind: proof.subject_digest for proof in proofs}
        expected.pop(EvidenceVerificationProofKind.AUTHENTICATION)
        if (
            actual != expected
            or len(proofs) != 4
            or any(
                proof.receipt_digest != receipt.receipt_digest
                or proof.trust_anchor_id != trust_anchor_id
                for proof in proofs
            )
        ):
            raise ValueError("decision evidence provider readback proofs mismatched")
        return tuple(sorted(proofs, key=lambda proof: proof.kind.value))


class AzureBlobDecisionEvidenceAdmissionProvider:
    """Resolve current admissions from immutable private Blob records."""

    def __init__(
        self,
        *,
        config: AzureBlobDecisionEvidenceProofConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = _AzureBlobDecisionEvidenceProofSource(
            config=config,
            http_client=http_client,
        )
        self._identity = identity
        self._clock = clock or (lambda: datetime.now(UTC))

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission | None:
        """Return an exact unexpired admission, or no admission when unavailable."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("decision evidence admission clock MUST be timezone-aware")
        try:
            token = await self._identity.get_token(_STORAGE_AUDIENCE)
            if (
                token.audience != _STORAGE_AUDIENCE
                or token.expires_at.tzinfo is None
                or token.expires_at.utcoffset() is None
                or token.expires_at <= now
            ):
                raise ValueError("decision evidence admission received an invalid storage token")
        except (httpx.HTTPError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
            _LOGGER.warning(
                "decision_evidence_admission_identity_unavailable",
                extra={"failure_type": type(exc).__name__},
            )
            return None
        lookup_digest = decision_evidence_lookup_digest(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
        ).removeprefix("sha256:")
        try:
            raw = await self._source.read(
                token=token.token,
                path=f"{_PROOF_PATH_PREFIX}admissions/{lookup_digest}.json",
            )
        except LookupError:
            return None
        except RuntimeError as exc:
            _LOGGER.warning(
                "decision_evidence_admission_storage_unavailable",
                extra={"failure_type": type(exc).__name__},
            )
            return None
        if not isinstance(raw, dict):
            raise DecisionEvidenceAdmissionRecordError(
                "retained decision evidence record MUST be an object"
            )
        retained = parse_decision_evidence_record(raw)
        try:
            return resolve_current_decision_evidence_admission(
                retained.admission,
                expected_evidence_digest=evidence_digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id=purpose_id,
                expected_source_revision=source_revision,
                evaluated_at=now,
            )
        except ValueError as exc:
            raise DecisionEvidenceAdmissionRecordError(
                "retained Blob admission does not match its content-addressed lookup"
            ) from exc


def _proof_path(kind: str, receipt_digest: str) -> str:
    if not receipt_digest.startswith("sha256:") or len(receipt_digest) != 71:
        raise ValueError("decision evidence receipt digest MUST be SHA-256")
    digest = receipt_digest.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("decision evidence receipt digest MUST be lowercase SHA-256")
    return f"{_PROOF_PATH_PREFIX}{kind}/{digest}.json"


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
    "AzureBlobDecisionEvidenceProofConfig",
    "AzureBlobDecisionEvidenceAdmissionProvider",
    "AzureBlobManagedIdentityAttestationReader",
    "AzureBlobProviderEvidenceReadbackReader",
    "AzureManagedIdentityAttestationReader",
    "AzureManagedIdentityDecisionEvidenceVerifier",
    "AzureProviderEvidenceReadbackReader",
]
