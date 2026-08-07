"""Managed-identity embedding adapter for API document search."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import (
    AdapterReadiness,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)

_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureEmbeddingConfig:
    endpoint: str
    deployment: str
    api_version: str = "2024-06-01"
    dimension: int = 384


class AzureEmbeddingModel:
    """Return one configured-dimensional embedding vector for search."""

    def __init__(
        self,
        *,
        config: AzureEmbeddingConfig,
        credential: ManagedIdentityCredential,
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
