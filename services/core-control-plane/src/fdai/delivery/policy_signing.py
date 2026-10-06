"""Azure Key Vault signing adapter for Mimir policy revisions."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from fdai.shared.providers.workload_identity import WorkloadIdentity

KEY_VAULT_AUDIENCE = "https://vault.azure.net"
DEFAULT_KEY_VAULT_API_VERSION = "7.4"
DEFAULT_POLICY_SIGNING_ALGORITHM = "RS256"


class KeyVaultHttpClient(Protocol):
    """Subset of the async HTTP client used by the Key Vault sign operation."""

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, str],
        timeout: float,
    ) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class AzureKeyVaultPolicyRevisionSigner:
    """Sign policy digests through a non-exportable Azure Key Vault key."""

    key_id: str
    identity: WorkloadIdentity
    http_client: KeyVaultHttpClient
    algorithm: str = DEFAULT_POLICY_SIGNING_ALGORITHM
    api_version: str = DEFAULT_KEY_VAULT_API_VERSION
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.key_id)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or ".vault.azure.net" not in parsed.hostname
            or "/keys/" not in parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("policy signing key id MUST be an Azure Key Vault key URL")
        if self.algorithm not in {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512"}:
            raise ValueError("policy signing algorithm MUST be an Azure Key Vault RSA sign alg")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise ValueError("policy signing timeout MUST be in (0, 30]")

    async def sign_policy_revision(self, *, policy_digest: str, revision_id: str) -> str:
        """Return a content-addressed reference to the Key Vault signature."""

        digest = hashlib.sha256(f"{revision_id}\n{policy_digest}".encode()).digest()
        token = await self.identity.get_token(KEY_VAULT_AUDIENCE)
        response = await self.http_client.post(
            f"{self.key_id.rstrip('/')}/sign?api-version={self.api_version}",
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "alg": self.algorithm,
                "value": _base64url(digest),
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body: Any = response.json()
        signature = body.get("value") if isinstance(body, dict) else None
        key_id = body.get("kid") if isinstance(body, dict) else None
        if not isinstance(signature, str) or not signature:
            raise RuntimeError("Key Vault sign response did not include a signature")
        if not isinstance(key_id, str) or not key_id.startswith(self.key_id.rstrip("/")):
            raise RuntimeError("Key Vault sign response did not match the configured key")
        signature_digest = hashlib.sha256(signature.encode("ascii")).hexdigest()
        return f"azure-key-vault:{key_id}:sha256:{signature_digest}"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


__all__ = [
    "AzureKeyVaultPolicyRevisionSigner",
    "DEFAULT_KEY_VAULT_API_VERSION",
    "DEFAULT_POLICY_SIGNING_ALGORITHM",
    "KEY_VAULT_AUDIENCE",
]
