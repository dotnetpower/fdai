"""Private Azure Blob storage for immutable operational-history archives."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import NoReturn
from urllib.parse import quote, urlparse

import httpx

from fdai.shared.providers.workload_identity import WorkloadIdentity

_STORAGE_AUDIENCE = "https://storage.azure.com/"
_STORAGE_API_VERSION = "2025-05-05"
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_PATH_PREFIX = "operational-history/"


@dataclass(frozen=True, slots=True)
class AzureBlobOperationalHistoryConfig:
    """Validated private Blob container binding."""

    container_url: str
    request_timeout_seconds: float = 60.0

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
            raise ValueError("operational history container URL MUST identify one HTTPS container")
        if self.request_timeout_seconds <= 0:
            raise ValueError("operational history request timeout MUST be positive")


class AzureBlobOperationalHistoryArtifactStore:
    """Managed-identity, content-addressed operational history artifact store."""

    def __init__(
        self,
        *,
        config: AzureBlobOperationalHistoryConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._container_url = config.container_url.rstrip("/")
        self._timeout = config.request_timeout_seconds
        self._identity = identity
        self._http = http_client

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        _validate_digest(digest)
        if not content or len(content) > _MAX_ARTIFACT_BYTES:
            raise ValueError("operational history artifact size is outside its bound")
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("operational history artifact digest mismatch")
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-None-Match": "*",
                "x-ms-blob-type": "BlockBlob",
                "x-ms-meta-fdai_sha256": digest,
            }
        )
        response = await self._request(
            "PUT",
            self._blob_url(storage_ref),
            headers,
            content,
        )
        if response.status_code == 201:
            return True
        if response.status_code in {409, 412}:
            existing = await self.get(storage_ref)
            if existing == content:
                return False
            raise ValueError("operational history artifact reference collision")
        _raise_storage_error(response)

    async def get(self, storage_ref: str) -> bytes | None:
        response = await self._request(
            "GET",
            self._blob_url(storage_ref),
            await self._headers(),
            None,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            _raise_storage_error(response)
        content = bytes(response.content)
        expected = response.headers.get("x-ms-meta-fdai_sha256", "")
        _validate_digest(expected)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("operational history stored artifact digest mismatch")
        return content

    async def _headers(self) -> dict[str, str]:
        identity_token = await self._identity.get_token(_STORAGE_AUDIENCE)
        return {
            "Authorization": "Bearer " + identity_token.token,
            "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
            "x-ms-version": _STORAGE_API_VERSION,
        }

    async def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        content: bytes | None,
    ) -> httpx.Response:
        try:
            return await self._http.request(
                method,
                url,
                headers=headers,
                content=content,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("operational history artifact storage request failed") from exc

    def _blob_url(self, storage_ref: str) -> str:
        segments = storage_ref.split("/")
        if (
            not storage_ref.startswith(_PATH_PREFIX)
            or "%" in storage_ref
            or "\\" in storage_ref
            or any(not segment or segment in {".", ".."} for segment in segments)
        ):
            raise ValueError("operational history storage_ref is unsafe")
        encoded = "/".join(quote(segment, safe="-._") for segment in segments)
        return f"{self._container_url}/{encoded}"


def _validate_digest(value: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("operational history digest MUST be lowercase SHA-256")


def _raise_storage_error(response: httpx.Response) -> NoReturn:
    raise RuntimeError(f"operational history artifact storage returned HTTP {response.status_code}")


__all__ = [
    "AzureBlobOperationalHistoryArtifactStore",
    "AzureBlobOperationalHistoryConfig",
]
