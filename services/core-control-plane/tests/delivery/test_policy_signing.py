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
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        self.requests.append(
            {"url": url, "headers": dict(headers), "json": dict(json), "timeout": timeout}
        )
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "kid": "https://fdai-example.vault.azure.net/keys/policy-signing/v1",
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

    signature_ref = await signer.sign_policy_revision(
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
    assert signature_ref.startswith(
        "azure-key-vault:https://fdai-example.vault.azure.net/keys/policy-signing/v1"
    )
    assert "signed-digest" not in signature_ref


def test_key_vault_policy_signer_rejects_non_key_urls() -> None:
    with pytest.raises(ValueError, match="Key Vault key URL"):
        AzureKeyVaultPolicyRevisionSigner(
            key_id="https://fdai-example.vault.azure.net/secrets/policy-signing",
            identity=_Identity([]),
            http_client=_Http(),
        )
