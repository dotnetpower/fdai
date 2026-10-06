from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.delivery.policy_signing import (
    KEY_VAULT_AUDIENCE,
    AzureKeyVaultPolicyRevisionSigner,
)
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.policy_administration import (
    AdmissionPolicyContent,
    PolicyKind,
    PolicyRevisionRecord,
    PolicyRevisionSignature,
    PolicyValidationResult,
)


@dataclass
class _Identity:
    audiences: list[str]

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="token-value",
            audience=audience,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


class _Http:
    def __init__(
        self,
        *,
        kid: str = "https://fdai-example.vault.azure.net/keys/policy-signing/v1",
        exportable: bool = False,
        release_policy: dict[str, object] | None = None,
        verified: bool = True,
    ) -> None:
        self.kid = kid
        self.exportable = exportable
        self.release_policy = release_policy
        self.verified = verified
        self.requests: list[dict[str, Any]] = []

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        self.requests.append(
            {"method": "GET", "url": url, "headers": dict(headers), "timeout": timeout}
        )
        body: dict[str, object] = {
            "key": {"kid": self.kid},
            "attributes": {"exportable": self.exportable},
        }
        if self.release_policy is not None:
            body["release_policy"] = self.release_policy
        return httpx.Response(200, request=httpx.Request("GET", url), json=body)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        self.requests.append(
            {
                "method": "POST",
                "url": url,
                "headers": dict(headers),
                "json": dict(json),
                "timeout": timeout,
            }
        )
        if url.endswith("/verify?api-version=7.4"):
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"value": self.verified},
            )
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "kid": self.kid,
                "value": "signed-digest",
            },
        )


@pytest.mark.asyncio
async def test_key_vault_policy_signer_uses_non_exportable_sign_operation() -> None:
    identity = _Identity([])
    http = _Http()
    signer = AzureKeyVaultPolicyRevisionSigner(
        key_id="https://fdai-example.vault.azure.net/keys/policy-signing",
        identity=identity,
        http_client=http,
    )

    signature = await signer.sign_policy_revision(
        policy_digest="sha256:" + "a" * 64,
        revision_id="policy-r1",
    )

    assert identity.audiences == [KEY_VAULT_AUDIENCE]
    assert len(http.requests) == 1
    request = http.requests[0]
    assert request["url"].endswith("/keys/policy-signing/sign?api-version=7.4")
    assert request["json"]["alg"] == "RS256"
    assert request["json"]["value"]
    assert request["headers"]["Authorization"] == "Bearer token-value"
    assert signature.key_id == "https://fdai-example.vault.azure.net/keys/policy-signing/v1"
    assert signature.signature_base64 == "signed-digest"
    assert signature.algorithm == "RS256"


@pytest.mark.asyncio
async def test_key_vault_policy_signer_verifies_stored_signature() -> None:
    signer = AzureKeyVaultPolicyRevisionSigner(
        key_id="https://fdai-example.vault.azure.net/keys/policy-signing",
        identity=_Identity([]),
        http_client=_Http(),
    )

    assert await signer.verify_policy_revision_signature(_record(_signature())) is True


@pytest.mark.parametrize("algorithm", ["RS384", "RS512", "PS384", "PS512"])
def test_key_vault_policy_signer_rejects_algorithms_without_sha256_digest(
    algorithm: str,
) -> None:
    with pytest.raises(ValueError, match="RS256 or PS256"):
        AzureKeyVaultPolicyRevisionSigner(
            key_id="https://fdai-example.vault.azure.net/keys/policy-signing",
            identity=_Identity([]),
            http_client=_Http(),
            algorithm=algorithm,
        )


def test_key_vault_policy_signer_rejects_lookalike_hosts() -> None:
    with pytest.raises(ValueError, match="Key Vault key URL"):
        AzureKeyVaultPolicyRevisionSigner(
            key_id="https://fdai-example.vault.azure.net.evil.example/keys/policy-signing",
            identity=_Identity([]),
            http_client=_Http(),
        )


@pytest.mark.asyncio
async def test_key_vault_policy_signer_rejects_wrong_response_key() -> None:
    signer = AzureKeyVaultPolicyRevisionSigner(
        key_id="https://fdai-example.vault.azure.net/keys/policy-signing",
        identity=_Identity([]),
        http_client=_Http(kid="https://fdai-example.vault.azure.net/keys/policy-other/v1"),
    )

    with pytest.raises(RuntimeError, match="configured key"):
        await signer.sign_policy_revision(policy_digest="sha256:" + "a" * 64, revision_id="r1")


@pytest.mark.asyncio
async def test_key_vault_policy_signer_refuses_exportable_or_releasable_keys() -> None:
    with pytest.raises(RuntimeError, match="non-exportable"):
        await AzureKeyVaultPolicyRevisionSigner.create_verified(
            key_id="https://fdai-example.vault.azure.net/keys/policy-signing",
            identity=_Identity([]),
            http_client=_Http(exportable=True),
        )
    with pytest.raises(RuntimeError, match="release policy"):
        await AzureKeyVaultPolicyRevisionSigner.create_verified(
            key_id="https://fdai-example.vault.azure.net/keys/policy-signing",
            identity=_Identity([]),
            http_client=_Http(release_policy={"contentType": "application/json"}),
        )


def test_key_vault_policy_signer_rejects_non_key_urls() -> None:
    with pytest.raises(ValueError, match="Key Vault key URL"):
        AzureKeyVaultPolicyRevisionSigner(
            key_id="https://fdai-example.vault.azure.net/secrets/policy-signing",
            identity=_Identity([]),
            http_client=_Http(),
        )


def _signature(
    *,
    key_id: str = "https://fdai-example.vault.azure.net/keys/policy-signing/v1",
    signature_base64: str = "signed-digest",
) -> PolicyRevisionSignature:
    return PolicyRevisionSignature(
        key_id=key_id,
        algorithm="RS256",
        signature_base64=signature_base64,
    )


def _record(signature: PolicyRevisionSignature | None) -> PolicyRevisionRecord:
    return PolicyRevisionRecord(
        revision_id="policy-r1",
        policy_kind=PolicyKind.ADMISSION,
        content_digest="sha256:" + "a" * 64,
        content=AdmissionPolicyContent(
            rego="package fdai.policy\nallow := true\n",
            action_type_modes={},
            policy_tests=({"rego": "package fdai.policy\n test_allow if { allow }\n"},),
        ),
        signature_ref=(signature.key_id if signature is not None else "legacy"),
        signature=signature,
        author_principal="policy-admin",
        reason="Reviewed policy change for a bounded installation scope.",
        created_at=datetime.now(UTC),
        validation=PolicyValidationResult(
            rego_valid=True,
            release_maximums_valid=True,
            policy_tests_valid=True,
            validation_digest="sha256:" + "b" * 64,
        ),
        diff_digest="sha256:" + "c" * 64,
    )
