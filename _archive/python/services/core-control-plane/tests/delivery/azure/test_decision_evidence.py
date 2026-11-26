"""Azure Managed Identity decision-evidence verifier tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.decision_evidence import (
    AzureBlobDecisionEvidenceAdmissionProvider,
    AzureBlobDecisionEvidenceProofConfig,
    AzureBlobManagedIdentityAttestationReader,
    AzureBlobProviderEvidenceReadbackReader,
    AzureManagedIdentityDecisionEvidenceVerifier,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    RetainedDecisionEvidence,
    decision_evidence_record_mapping,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    EvidenceVerificationProofKind,
    expected_verification_subjects,
)

_NOW = datetime(2026, 8, 29, 5, 0, tzinfo=UTC)
_AUDIENCE = "https://management.azure.com/.default"
_DIGESTS = tuple("sha256:" + char * 64 for char in "abcdef0")


def _receipt() -> DecisionCriticalEvidenceReceipt:
    values = {
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
    return DecisionCriticalEvidenceReceipt.model_validate(
        {
            **values,
            "receipt_digest": decision_critical_evidence_receipt_digest(**values),
        }
    )


class _Identity:
    def __init__(
        self,
        *,
        token_audience: str = _AUDIENCE,
        expires_at: datetime = _NOW + timedelta(minutes=30),
    ) -> None:
        self.audiences: list[str] = []
        self._token_audience = token_audience
        self._expires_at = expires_at

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="transient-token",
            audience=self._token_audience,
            expires_at=self._expires_at,
        )


class _FailingIdentity:
    async def get_token(self, audience: str) -> IdentityToken:
        raise httpx.ConnectError("identity unavailable", request=httpx.Request("GET", audience))


def _proof(kind, subject, receipt_digest):
    return DecisionEvidenceVerificationProof(
        kind=kind,
        receipt_digest=receipt_digest,
        subject_digest=subject,
        proof_digest="sha256:" + kind.value[0] * 64,
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
        issued_at=_NOW + timedelta(minutes=2),
        valid_until=_NOW + timedelta(minutes=8),
    )


async def test_azure_verifier_uses_transient_token_and_returns_content_free_bundle() -> None:
    receipt = _receipt()
    identity = _Identity()
    seen_tokens: list[str] = []
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )

    class _Attestation:
        async def attest(self, *, token, receipt, trust_anchor_id):
            del trust_anchor_id
            seen_tokens.append(token)
            return _proof(
                EvidenceVerificationProofKind.AUTHENTICATION,
                receipt.authentication_evidence_digest,
                receipt.receipt_digest,
            )

    class _Readback:
        async def readback(self, *, token, receipt, trust_anchor_id):
            del trust_anchor_id
            seen_tokens.append(token)
            return tuple(
                _proof(kind, subject, receipt.receipt_digest)
                for kind, subject in subjects.items()
                if kind is not EvidenceVerificationProofKind.AUTHENTICATION
            )

    bundle = await AzureManagedIdentityDecisionEvidenceVerifier(
        identity=identity,
        attestation_reader=_Attestation(),
        readback_reader=_Readback(),
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        clock=lambda: _NOW + timedelta(minutes=3),
    ).verify(
        receipt,
        trust_anchor_id="azure:managed-identity",
    )

    assert identity.audiences == [_AUDIENCE]
    assert seen_tokens == ["transient-token", "transient-token"]
    assert len(bundle.proofs) == 5
    assert bundle.execution_authority is False
    assert "transient-token" not in bundle.model_dump_json()


@pytest.mark.parametrize(
    ("token_audience", "expires_at"),
    [
        ("https://vault.azure.net/.default", _NOW + timedelta(minutes=30)),
        (_AUDIENCE, _NOW + timedelta(minutes=3)),
    ],
)
async def test_azure_verifier_rejects_wrong_audience_and_expired_token(
    token_audience: str,
    expires_at: datetime,
) -> None:
    class _UnusedAttestation:
        async def attest(self, **kwargs):
            raise AssertionError(f"unexpected attestation call: {kwargs}")

    class _UnusedReadback:
        async def readback(self, **kwargs):
            raise AssertionError(f"unexpected readback call: {kwargs}")

    verifier = AzureManagedIdentityDecisionEvidenceVerifier(
        identity=_Identity(token_audience=token_audience, expires_at=expires_at),
        attestation_reader=_UnusedAttestation(),
        readback_reader=_UnusedReadback(),
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        clock=lambda: _NOW + timedelta(minutes=3),
    )

    with pytest.raises(ValueError, match="invalid managed identity token"):
        await verifier.verify(
            _receipt(),
            trust_anchor_id="azure:managed-identity",
        )


async def test_azure_verifier_rejects_naive_token_expiry() -> None:
    class _UnusedAttestation:
        async def attest(self, **kwargs):
            raise AssertionError(f"unexpected attestation call: {kwargs}")

    class _UnusedReadback:
        async def readback(self, **kwargs):
            raise AssertionError(f"unexpected readback call: {kwargs}")

    verifier = AzureManagedIdentityDecisionEvidenceVerifier(
        identity=_Identity(expires_at=datetime(2026, 8, 29, 5, 30)),
        attestation_reader=_UnusedAttestation(),
        readback_reader=_UnusedReadback(),
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        clock=lambda: _NOW + timedelta(minutes=3),
    )

    with pytest.raises(ValueError, match="token expiry MUST be timezone-aware"):
        await verifier.verify(
            _receipt(),
            trust_anchor_id="azure:managed-identity",
        )


async def test_blob_readers_load_content_addressed_proofs_without_retaining_token() -> None:
    receipt = _receipt()
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    proofs = tuple(
        _proof(kind, subject, receipt.receipt_digest) for kind, subject in subjects.items()
    )
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer transient-token"
        seen_paths.append(request.url.path)
        if "/authentication/" in request.url.path:
            payload: object = proofs[0].model_dump(mode="json")
        else:
            payload = {"proofs": [proof.model_dump(mode="json") for proof in proofs[1:]]}
        content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return httpx.Response(
            200,
            content=content,
            headers={"x-ms-meta-fdaisha256": hashlib.sha256(content).hexdigest()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        config = AzureBlobDecisionEvidenceProofConfig(container_url="https://example.com/evidence")
        bundle = await AzureManagedIdentityDecisionEvidenceVerifier(
            identity=_Identity(),
            attestation_reader=AzureBlobManagedIdentityAttestationReader(
                config=config,
                http_client=client,
            ),
            readback_reader=AzureBlobProviderEvidenceReadbackReader(
                config=config,
                http_client=client,
            ),
            verifier_id="azure.readback",
            verifier_version="1.0.0",
            clock=lambda: _NOW + timedelta(minutes=3),
        ).verify(
            receipt,
            trust_anchor_id="azure:managed-identity",
        )

    digest = receipt.receipt_digest.removeprefix("sha256:")
    assert seen_paths == [
        f"/evidence/decision-evidence/v1/authentication/{digest}.json",
        f"/evidence/decision-evidence/v1/readback/{digest}.json",
    ]
    assert bundle.proofs == tuple(sorted(proofs, key=lambda proof: proof.kind.value))
    assert "transient-token" not in bundle.model_dump_json()


async def test_blob_reader_rejects_stored_content_digest_mismatch() -> None:
    receipt = _receipt()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_proof(
                EvidenceVerificationProofKind.AUTHENTICATION,
                receipt.authentication_evidence_digest,
                receipt.receipt_digest,
            ).model_dump(mode="json"),
            headers={"x-ms-meta-fdaisha256": "0" * 64},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureBlobManagedIdentityAttestationReader(
            config=AzureBlobDecisionEvidenceProofConfig(
                container_url="https://example.com/evidence"
            ),
            http_client=client,
        )
        with pytest.raises(ValueError, match="digest mismatched"):
            await reader.attest(
                token="transient-token",
                receipt=receipt,
                trust_anchor_id="azure:managed-identity",
            )


async def test_blob_readback_rejects_missing_or_duplicate_proof_kinds() -> None:
    receipt = _receipt()
    proof = _proof(
        EvidenceVerificationProofKind.EVIDENCE,
        receipt.evidence_digest,
        receipt.receipt_digest,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        payload = {"proofs": [proof.model_dump(mode="json")] * 4}
        content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return httpx.Response(
            200,
            content=content,
            headers={"x-ms-meta-fdaisha256": hashlib.sha256(content).hexdigest()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureBlobProviderEvidenceReadbackReader(
            config=AzureBlobDecisionEvidenceProofConfig(
                container_url="https://example.com/evidence"
            ),
            http_client=client,
        )
        with pytest.raises(ValueError, match="proofs mismatched"):
            await reader.readback(
                token="transient-token",
                receipt=receipt,
                trust_anchor_id="azure:managed-identity",
            )


async def test_blob_admission_provider_resolves_an_exact_current_record() -> None:
    receipt = _receipt()
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    proofs = tuple(
        _proof(kind, subject, receipt.receipt_digest) for kind, subject in subjects.items()
    )
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
        verified_at=_NOW + timedelta(minutes=2),
        valid_until=_NOW + timedelta(minutes=8),
        proofs=proofs,
    )
    admission = DecisionEvidenceAdmission(
        receipt_digest=receipt.receipt_digest,
        verification_bundle_digest=bundle.bundle_digest,
        evidence_digest=receipt.evidence_digest,
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        source_revision=receipt.source_revision,
        verified_at=bundle.verified_at,
        valid_until=bundle.valid_until,
    )
    record = decision_evidence_record_mapping(
        RetainedDecisionEvidence(
            receipt=receipt,
            verification_bundle=bundle,
            admission=admission,
        )
    )
    content = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/decision-evidence/v1/admissions/" in request.url.path
        return httpx.Response(
            200,
            content=content,
            headers={"x-ms-meta-fdaisha256": hashlib.sha256(content).hexdigest()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureBlobDecisionEvidenceAdmissionProvider(
            config=AzureBlobDecisionEvidenceProofConfig(
                container_url="https://example.com/evidence"
            ),
            identity=_Identity(token_audience="https://storage.azure.com/"),
            http_client=client,
            clock=lambda: _NOW + timedelta(minutes=3),
        )
        resolved = await provider.admit(
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
        )

    assert resolved == admission


async def test_blob_admission_provider_returns_none_for_missing_record() -> None:
    receipt = _receipt()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureBlobDecisionEvidenceAdmissionProvider(
            config=AzureBlobDecisionEvidenceProofConfig(
                container_url="https://example.com/evidence"
            ),
            identity=_Identity(token_audience="https://storage.azure.com/"),
            http_client=client,
            clock=lambda: _NOW + timedelta(minutes=3),
        )
        resolved = await provider.admit(
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
        )

    assert resolved is None


async def test_blob_admission_provider_degrades_on_storage_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt = _receipt()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureBlobDecisionEvidenceAdmissionProvider(
            config=AzureBlobDecisionEvidenceProofConfig(
                container_url="https://example.com/evidence"
            ),
            identity=_Identity(token_audience="https://storage.azure.com/"),
            http_client=client,
            clock=lambda: _NOW + timedelta(minutes=3),
        )
        resolved = await provider.admit(
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
        )

    assert resolved is None
    assert "decision_evidence_admission_storage_unavailable" in caplog.messages


async def test_blob_admission_provider_degrades_on_identity_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt = _receipt()

    async with httpx.AsyncClient() as client:
        provider = AzureBlobDecisionEvidenceAdmissionProvider(
            config=AzureBlobDecisionEvidenceProofConfig(
                container_url="https://example.com/evidence"
            ),
            identity=_FailingIdentity(),
            http_client=client,
            clock=lambda: _NOW + timedelta(minutes=3),
        )
        resolved = await provider.admit(
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
        )

    assert resolved is None
    assert "decision_evidence_admission_identity_unavailable" in caplog.messages
