"""Persist one Teams Workflows endpoint in an Azure Key Vault secret."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_VAULT_SCOPE = "https://vault.azure.net/.default"
_API_VERSION = "7.4"
_SECRET_NAME = re.compile(r"^[A-Za-z0-9-]{1,127}$")
_SECRET_VERSION = re.compile(r"^[A-Za-z0-9]{1,64}$")

TokenProvider = Callable[[str], Awaitable[str]]


class TeamsWorkflowBindingError(RuntimeError):
    """A secret write or independent verification did not complete."""


class AsyncHttpClient(Protocol):
    """Perform bounded Key Vault data-plane requests."""

    async def put(self, url: str, **kwargs: Any) -> httpx.Response: ...

    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


class BoundedHttpClient:
    """Use a fresh bounded client so the binding adapter owns no lifecycle."""

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            return await client.put(url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            return await client.get(url, **kwargs)


@dataclass(frozen=True, slots=True)
class TeamsWorkflowBindingConfig:
    """Identify the dedicated Key Vault secret used for one Teams endpoint."""

    vault_url: str
    secret_name: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.vault_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".vault.azure.net")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Teams Workflow Key Vault URL MUST be a public-cloud vault origin")
        if _SECRET_NAME.fullmatch(self.secret_name) is None:
            raise ValueError("Teams Workflow Key Vault secret name is invalid")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("Teams Workflow Key Vault timeout MUST be in (0, 60]")


@dataclass(frozen=True, slots=True)
class SavedTeamsWorkflowBinding:
    """Describe a verified secret version without returning its value."""

    version: str
    endpoint_digest: str


@dataclass(frozen=True, slots=True)
class LoadedTeamsWorkflowBinding:
    """Carry the verified endpoint only inside the server process."""

    webhook_url: str = field(repr=False)
    version: str
    endpoint_digest: str


class TeamsWorkflowBindingStore(Protocol):
    """Persist and independently verify a Teams Workflows endpoint."""

    async def save_and_verify(
        self,
        *,
        webhook_url: str,
        request_id: str,
    ) -> LoadedTeamsWorkflowBinding: ...

    async def load(self) -> LoadedTeamsWorkflowBinding | None: ...


class LocalBindingStateStore(Protocol):
    """Persist encrypted local binding state in the Operator-owned store."""

    async def read_state(self, key: str) -> dict[str, object] | None: ...

    async def write_state(self, key: str, value: Mapping[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class LocalEncryptedTeamsWorkflowBindingStore:
    """Persist only ciphertext in the loopback development database."""

    store: LocalBindingStateStore
    key_material: str = field(repr=False)

    async def save_and_verify(
        self,
        *,
        webhook_url: str,
        request_id: str,
    ) -> LoadedTeamsWorkflowBinding:
        cipher = self._cipher()
        version = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:32]
        digest = hashlib.sha256(webhook_url.encode("utf-8")).hexdigest()
        ciphertext = cipher.encrypt(webhook_url.encode("utf-8")).decode("ascii")
        await self.store.write_state(
            "operator-teams-workflow-binding:active",
            {
                "kind": "operator.local-encrypted-teams-workflow-binding",
                "version": version,
                "endpoint_digest": digest,
                "ciphertext": ciphertext,
            },
        )
        saved = await self.store.read_state("operator-teams-workflow-binding:active")
        saved_ciphertext = saved.get("ciphertext") if saved is not None else None
        if (
            saved is None
            or saved.get("version") != version
            or saved.get("endpoint_digest") != digest
            or not isinstance(saved_ciphertext, str)
        ):
            raise TeamsWorkflowBindingError(
                "Local Teams Workflow binding verification metadata did not match"
            )
        try:
            verified = cipher.decrypt(saved_ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise TeamsWorkflowBindingError(
                "Local Teams Workflow binding verification failed"
            ) from exc
        if verified != webhook_url:
            raise TeamsWorkflowBindingError(
                "Local Teams Workflow binding verification did not match the saved value"
            )
        return LoadedTeamsWorkflowBinding(
            webhook_url=verified,
            version=version,
            endpoint_digest=digest,
        )

    async def load(self) -> LoadedTeamsWorkflowBinding | None:
        saved = await self.store.read_state("operator-teams-workflow-binding:active")
        if saved is None:
            return None
        version = saved.get("version")
        digest = saved.get("endpoint_digest")
        ciphertext = saved.get("ciphertext")
        if (
            saved.get("kind") != "operator.local-encrypted-teams-workflow-binding"
            or not isinstance(version, str)
            or not isinstance(digest, str)
            or not isinstance(ciphertext, str)
        ):
            raise TeamsWorkflowBindingError("Local Teams Workflow binding is malformed")
        try:
            webhook_url = self._cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise TeamsWorkflowBindingError(
                "Local Teams Workflow binding decryption failed"
            ) from exc
        if hashlib.sha256(webhook_url.encode("utf-8")).hexdigest() != digest:
            raise TeamsWorkflowBindingError("Local Teams Workflow binding digest mismatch")
        return LoadedTeamsWorkflowBinding(
            webhook_url=webhook_url,
            version=version,
            endpoint_digest=digest,
        )

    def _cipher(self) -> Fernet:
        if not self.key_material:
            raise TeamsWorkflowBindingError(
                "Local Teams Workflow binding key material is unavailable"
            )
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"fdai/operator/teams-workflow-binding/v1",
        ).derive(self.key_material.encode("utf-8"))
        return Fernet(base64.urlsafe_b64encode(derived))


@dataclass(frozen=True, slots=True)
class KeyVaultTeamsWorkflowBindingStore:
    """Write a new Key Vault secret version and read that exact version back."""

    config: TeamsWorkflowBindingConfig
    token_provider: TokenProvider
    http_client: AsyncHttpClient = field(default_factory=BoundedHttpClient)

    async def save_and_verify(
        self,
        *,
        webhook_url: str,
        request_id: str,
    ) -> LoadedTeamsWorkflowBinding:
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                return await self._save_and_verify(webhook_url=webhook_url, request_id=request_id)
        except TimeoutError as exc:
            raise TeamsWorkflowBindingError("Teams Workflow binding save timed out") from exc
        except httpx.HTTPError as exc:
            raise TeamsWorkflowBindingError(
                "Teams Workflow binding provider request failed"
            ) from exc

    async def load(self) -> LoadedTeamsWorkflowBinding | None:
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                token = await self.token_provider(KEY_VAULT_SCOPE)
                if not token:
                    raise TeamsWorkflowBindingError(
                        "Teams Workflow binding credential is unavailable"
                    )
                response = await self.http_client.get(
                    self._secret_url(),
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=self.config.timeout_seconds,
                    follow_redirects=False,
                )
                if response.status_code < 200 or response.status_code >= 300:
                    raise TeamsWorkflowBindingError(
                        f"Teams Workflow binding read failed with status {response.status_code}"
                    )
                envelope = self._envelope(response)
                tags = envelope.get("tags")
                if (
                    not isinstance(tags, Mapping)
                    or tags.get("fdai-purpose") != "teams-workflow-binding"
                ):
                    return None
                value = envelope.get("value")
                if not isinstance(value, str):
                    raise TeamsWorkflowBindingError(
                        "Teams Workflow binding read omitted the secret value"
                    )
                version = self._version(response)
                return LoadedTeamsWorkflowBinding(
                    webhook_url=value,
                    version=version,
                    endpoint_digest=hashlib.sha256(value.encode("utf-8")).hexdigest(),
                )
        except TimeoutError as exc:
            raise TeamsWorkflowBindingError("Teams Workflow binding read timed out") from exc
        except httpx.HTTPError as exc:
            raise TeamsWorkflowBindingError(
                "Teams Workflow binding provider request failed"
            ) from exc

    async def _save_and_verify(
        self,
        *,
        webhook_url: str,
        request_id: str,
    ) -> LoadedTeamsWorkflowBinding:
        token = await self.token_provider(KEY_VAULT_SCOPE)
        if not token:
            raise TeamsWorkflowBindingError("Teams Workflow binding credential is unavailable")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = await self.http_client.put(
            self._secret_url(),
            headers=headers,
            json={
                "value": webhook_url,
                "tags": {
                    "fdai-purpose": "teams-workflow-binding",
                    "fdai-request-id": request_id,
                },
            },
            timeout=self.config.timeout_seconds,
            follow_redirects=False,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise TeamsWorkflowBindingError(
                f"Teams Workflow binding save failed with status {response.status_code}"
            )
        version = self._version(response)
        verified = await self.http_client.get(
            self._secret_url(version),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=self.config.timeout_seconds,
            follow_redirects=False,
        )
        if verified.status_code < 200 or verified.status_code >= 300:
            raise TeamsWorkflowBindingError(
                f"Teams Workflow binding verification failed with status {verified.status_code}"
            )
        envelope = self._envelope(verified)
        value = envelope.get("value")
        if not isinstance(value, str) or value != webhook_url:
            raise TeamsWorkflowBindingError(
                "Teams Workflow binding verification did not match the saved value"
            )
        return LoadedTeamsWorkflowBinding(
            webhook_url=value,
            version=version,
            endpoint_digest=hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )

    def _secret_url(self, version: str | None = None) -> str:
        suffix = f"/{quote(version, safe='')}" if version is not None else ""
        return (
            f"{self.config.vault_url.rstrip('/')}/secrets/"
            f"{quote(self.config.secret_name, safe='')}{suffix}?api-version={_API_VERSION}"
        )

    def _version(self, response: httpx.Response) -> str:
        secret_id = self._envelope(response).get("id")
        if not isinstance(secret_id, str):
            raise TeamsWorkflowBindingError(
                "Teams Workflow binding save response omitted the secret id"
            )
        parsed = urlsplit(secret_id)
        expected = urlsplit(self.config.vault_url)
        parts = parsed.path.rstrip("/").split("/")
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected.hostname
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or len(parts) != 4
            or parts[1] != "secrets"
            or parts[2] != self.config.secret_name
            or _SECRET_VERSION.fullmatch(parts[3]) is None
        ):
            raise TeamsWorkflowBindingError(
                "Teams Workflow binding save response contained an invalid secret id"
            )
        return parts[3]

    @staticmethod
    def _envelope(response: httpx.Response) -> Mapping[str, object]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise TeamsWorkflowBindingError("Teams Workflow binding response was invalid") from exc
        if not isinstance(payload, Mapping):
            raise TeamsWorkflowBindingError("Teams Workflow binding response was invalid")
        return payload


__all__ = [
    "KEY_VAULT_SCOPE",
    "BoundedHttpClient",
    "KeyVaultTeamsWorkflowBindingStore",
    "LoadedTeamsWorkflowBinding",
    "LocalEncryptedTeamsWorkflowBindingStore",
    "SavedTeamsWorkflowBinding",
    "TeamsWorkflowBindingError",
    "TeamsWorkflowBindingConfig",
    "TeamsWorkflowBindingStore",
]
