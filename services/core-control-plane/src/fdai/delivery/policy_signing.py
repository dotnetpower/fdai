"""Azure Key Vault signing adapter for Mimir policy revisions."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from fdai_service_contracts.policy_administration import (
    PolicyRevisionRecord,
    PolicyRevisionSignature,
    policy_content_digest,
    policy_revision_signature_message,
)

from fdai.shared.providers.workload_identity import WorkloadIdentity

KEY_VAULT_AUDIENCE = "https://vault.azure.net"
DEFAULT_KEY_VAULT_API_VERSION = "7.4"
DEFAULT_POLICY_SIGNING_ALGORITHM = "RS256"
SUPPORTED_POLICY_SIGNING_ALGORITHMS = frozenset({"RS256", "PS256"})


class KeyVaultHttpClient(Protocol):
    """Subset of the async HTTP client used by the Key Vault sign operation."""

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response: ...

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
        _key_parts(self.key_id, require_version=False)
        if self.algorithm not in SUPPORTED_POLICY_SIGNING_ALGORITHMS:
            raise ValueError("policy signing algorithm MUST be RS256 or PS256")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise ValueError("policy signing timeout MUST be in (0, 30]")

    @classmethod
    async def create_verified(
        cls,
        *,
        key_id: str,
        identity: WorkloadIdentity,
        http_client: KeyVaultHttpClient,
        algorithm: str = DEFAULT_POLICY_SIGNING_ALGORITHM,
        api_version: str = DEFAULT_KEY_VAULT_API_VERSION,
        timeout_seconds: float = 10.0,
    ) -> AzureKeyVaultPolicyRevisionSigner:
        """Build a signer after verifying the key cannot be exported."""

        signer = cls(
            key_id=key_id,
            identity=identity,
            http_client=http_client,
            algorithm=algorithm,
            api_version=api_version,
            timeout_seconds=timeout_seconds,
        )
        await signer.verify_key_configuration()
        return signer

    async def verify_key_configuration(self) -> None:
        """Refuse exportable or release-policy-backed Key Vault keys."""

        response = await self.http_client.get(
            f"{self.key_id.rstrip('/')}?api-version={self.api_version}",
            headers=await self._headers(),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body: Any = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Key Vault key response did not include a JSON object")
        key = body.get("key")
        returned_key_id = key.get("kid") if isinstance(key, dict) else None
        if not isinstance(returned_key_id, str) or not _same_unversioned_key(
            returned_key_id, self.key_id
        ):
            raise RuntimeError("Key Vault key response did not match the configured key")
        attributes = body.get("attributes")
        if not isinstance(attributes, dict):
            raise RuntimeError("Key Vault key response did not include key attributes")
        if attributes.get("exportable") is True:
            raise RuntimeError("policy signing key MUST be non-exportable")
        if body.get("release_policy") is not None:
            raise RuntimeError("policy signing key MUST NOT have a release policy")

    async def sign_policy_revision(
        self, *, policy_digest: str, revision_id: str
    ) -> PolicyRevisionSignature:
        """Return raw Key Vault signature evidence for one revision."""

        digest = _policy_revision_digest(revision_id=revision_id, policy_digest=policy_digest)
        response = await self.http_client.post(
            f"{self.key_id.rstrip('/')}/sign?api-version={self.api_version}",
            headers=await self._headers(),
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
        if (
            not isinstance(key_id, str)
            or not _same_unversioned_key(key_id, self.key_id)
            or _key_parts(key_id, require_version=True).version is None
        ):
            raise RuntimeError("Key Vault sign response did not match the configured key")
        return PolicyRevisionSignature(
            key_id=key_id,
            algorithm=self.algorithm,  # type: ignore[arg-type]
            signature_base64=signature,
        )

    async def verify_policy_revision_signature(self, record: PolicyRevisionRecord) -> bool:
        """Verify one stored revision signature through Azure Key Vault."""

        signature = record.signature
        if signature is None:
            return False
        if policy_content_digest(record.content) != record.content_digest:
            return False
        if signature.algorithm not in SUPPORTED_POLICY_SIGNING_ALGORITHMS:
            return False
        try:
            if not _same_unversioned_key(signature.key_id, self.key_id):
                return False
            _key_parts(signature.key_id, require_version=True)
        except ValueError:
            return False
        digest = _policy_revision_digest(
            revision_id=record.revision_id,
            policy_digest=record.content_digest,
            message_format=signature.signed_message_format,
        )
        response = await self.http_client.post(
            f"{signature.key_id.rstrip('/')}/verify?api-version={self.api_version}",
            headers=await self._headers(),
            json={
                "alg": signature.algorithm,
                "digest": _base64url(digest),
                "value": signature.signature_base64,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body: Any = response.json()
        return isinstance(body, dict) and body.get("value") is True

    async def _headers(self) -> dict[str, str]:
        token = await self.identity.get_token(KEY_VAULT_AUDIENCE)
        return {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


@dataclass(frozen=True, slots=True)
class _KeyParts:
    host: str
    name: str
    version: str | None


def _key_parts(key_id: str, *, require_version: bool) -> _KeyParts:
    parsed = urlsplit(key_id)
    segments = tuple(part for part in parsed.path.split("/") if part)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not parsed.hostname.endswith(".vault.azure.net")
        or len(parsed.hostname.removesuffix(".vault.azure.net")) < 1
        or parsed.query
        or parsed.fragment
        or len(segments) not in {2, 3}
        or segments[0] != "keys"
        or not segments[1]
        or (require_version and len(segments) != 3)
    ):
        raise ValueError("policy signing key id MUST be an Azure Key Vault key URL")
    return _KeyParts(
        host=parsed.hostname,
        name=segments[1],
        version=segments[2] if len(segments) == 3 else None,
    )


def _same_unversioned_key(left: str, right: str) -> bool:
    left_parts = _key_parts(left, require_version=False)
    right_parts = _key_parts(right, require_version=False)
    return left_parts.host == right_parts.host and left_parts.name == right_parts.name


def _policy_revision_digest(
    *,
    revision_id: str,
    policy_digest: str,
    message_format: str = "fdai.policy-revision.v1",
) -> bytes:
    return hashlib.sha256(
        policy_revision_signature_message(
            revision_id=revision_id,
            policy_digest=policy_digest,
            message_format=message_format,
        )
    ).digest()


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


__all__ = [
    "AzureKeyVaultPolicyRevisionSigner",
    "DEFAULT_KEY_VAULT_API_VERSION",
    "DEFAULT_POLICY_SIGNING_ALGORITHM",
    "KEY_VAULT_AUDIENCE",
    "SUPPORTED_POLICY_SIGNING_ALGORITHMS",
]
