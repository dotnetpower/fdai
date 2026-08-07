"""Managed-identity embedding adapter for API document search."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from azure.identity.aio import ManagedIdentityCredential

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
