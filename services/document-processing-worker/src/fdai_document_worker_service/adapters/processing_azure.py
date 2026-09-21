"""Azure OCR and embedding adapters for document processing."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from fdai_service_contracts import (
    AdapterReadiness,
    DocumentVersion,
    ProviderUnavailableError,
    StructuralUnit,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
    unavailable_readiness,
)

from fdai_document_worker_service.adapters.processing_extraction_support import _ocr_units

_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureDocumentOcrConfig:
    endpoint: str
    api_version: str = "2024-11-30"
    operation_timeout_seconds: float = 180.0
    max_lines: int = 5000
    max_characters: int = 1_000_000
    max_response_bytes: int = 4_000_000

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("OCR endpoint MUST be an HTTPS origin")


class AzureDocumentIntelligenceOcr:
    """Call prebuilt-read with managed identity and bounded polling/output."""

    def __init__(
        self,
        *,
        config: AzureDocumentOcrConfig,
        credential: AsyncTokenCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._credential = credential
        self._client = client

    def readiness(self) -> AdapterReadiness:
        """Report validated OCR composition without requesting an Azure token."""
        return configured_readiness("document-intelligence-ocr")

    async def probe_readiness(self) -> AdapterReadiness:
        """Authenticate and list at most one OCR model without analyzing content."""
        adapter = "document-intelligence-ocr"
        try:
            async with asyncio.timeout(5.0):
                token = await self._credential.get_token(_COGNITIVE_SCOPE)
                response = await self._client.get(
                    f"{self._config.endpoint.rstrip('/')}/documentintelligence/documentModels",
                    params={"api-version": self._config.api_version, "top": "1"},
                    headers={"Authorization": f"Bearer {token.token}"},
                )
                response.raise_for_status()
                if len(response.content) > self._config.max_response_bytes:
                    return live_unavailable_readiness(adapter, "probe_response_too_large")
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        token = await self._credential.get_token(_COGNITIVE_SCOPE)
        url = (
            f"{self._config.endpoint.rstrip('/')}/documentintelligence/documentModels/"
            f"prebuilt-read:analyze?api-version={self._config.api_version}"
        )
        response = await self._client.post(
            url,
            content=content,
            headers={"Authorization": f"Bearer {token.token}", "Content-Type": version.media_type},
        )
        if response.status_code != 202:
            raise RuntimeError(f"OCR analyze request returned HTTP {response.status_code}")
        operation_url = response.headers.get("operation-location")
        if (
            not operation_url
            or urlparse(operation_url).hostname != urlparse(self._config.endpoint).hostname
        ):
            raise RuntimeError("OCR operation location is outside the configured origin")
        async with asyncio.timeout(self._config.operation_timeout_seconds):
            while True:
                result = await self._client.get(
                    operation_url,
                    headers={"Authorization": f"Bearer {token.token}"},
                )
                if len(result.content) > self._config.max_response_bytes:
                    raise RuntimeError("OCR response exceeded configured bounds")
                payload = result.json()
                status = payload.get("status")
                if status == "succeeded":
                    return _ocr_units(
                        payload,
                        self._config.max_lines,
                        self._config.max_characters,
                    )
                if status in {"failed", "canceled"}:
                    raise RuntimeError(f"OCR operation ended with status {status}")
                await asyncio.sleep(0.5)


class UnavailableImageOcr:
    """Fail closed when no OCR endpoint was configured for scanned content."""

    _REASON = "FDAI_OCR_ENDPOINT is not configured"

    def readiness(self) -> AdapterReadiness:
        return unavailable_readiness("document-intelligence-ocr", self._REASON)

    async def probe_readiness(self) -> AdapterReadiness:
        """Return the same explicit unavailability without external I/O."""
        return self.readiness()

    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        del version, content
        raise ProviderUnavailableError(self._REASON)


@dataclass(frozen=True, slots=True)
class AzureEmbeddingConfig:
    endpoint: str
    deployment: str
    api_version: str = "2024-06-01"
    dimension: int = 384


class EmbeddingModel(Protocol):
    """Generate fixed-dimensional vectors and expose live readiness."""

    def readiness(self) -> AdapterReadiness: ...

    async def probe_readiness(self) -> AdapterReadiness: ...

    async def embed(self, text: str) -> Sequence[float]: ...


class AzureEmbeddingModel:
    """Generate bounded embedding vectors with managed identity."""

    def __init__(
        self,
        *,
        config: AzureEmbeddingConfig,
        credential: AsyncTokenCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._credential = credential
        self._client = client

    def readiness(self) -> AdapterReadiness:
        """Report validated embedding composition without requesting a token."""
        return configured_readiness("azure-openai-embedding")

    async def probe_readiness(self) -> AdapterReadiness:
        """Generate one fixed minimal vector within a short timeout."""
        adapter = "azure-openai-embedding"
        try:
            async with asyncio.timeout(5.0):
                await self.embed("readiness")
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def embed(self, text: str) -> Sequence[float]:
        token = await self._credential.get_token(_COGNITIVE_SCOPE)
        response = await self._client.post(
            f"{self._config.endpoint.rstrip('/')}/openai/deployments/"
            f"{self._config.deployment}/embeddings",
            params={"api-version": self._config.api_version},
            headers={"Authorization": f"Bearer {token.token}"},
            json={"input": text, "dimensions": self._config.dimension},
        )
        response.raise_for_status()
        try:
            vector = response.json()["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("embedding response is missing data[0].embedding") from exc
        if not isinstance(vector, list) or len(vector) != self._config.dimension:
            raise RuntimeError("embedding response dimension does not match configuration")
        return tuple(float(value) for value in vector)
