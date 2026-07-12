"""AzureOpenAIEmbeddingModel - httpx-based embedding client."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import httpx

from fdai.core.metering.emitter import MeteringEmitter
from fdai.delivery.azure.llm.usage import extract_usage
from fdai.shared.providers.workload_identity import WorkloadIdentity

_COGNITIVE_SCOPE: Final[str] = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureOpenAIEmbeddingModelConfig:
    """Endpoint + deployment binding for one embedding capability."""

    endpoint: str
    """Custom-subdomain URL, e.g. ``https://<caf-openai-endpoint>.openai.azure.com``."""

    deployment: str
    """Deployment name as created by the Terraform module - matches the
    capability name in ``resolved-models.json``."""

    api_version: str = "2024-06-01"
    """Azure OpenAI data-plane API version."""

    dim: int = 1536
    """Vector dimensionality - MUST match the deployed family (e.g. 1536 for
    ``text-embedding-3-small``)."""

    timeout_seconds: float = 30.0


class AzureOpenAIEmbeddingModel:
    """Implements :class:`~fdai.core.tiers.t1_lightweight.tier.EmbeddingModel`.

    Kept intentionally small: one method, one endpoint, one auth path. Tests
    inject an :class:`httpx.MockTransport`-backed :class:`httpx.AsyncClient` so
    no live network is touched.
    """

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIEmbeddingModelConfig,
        metering: MeteringEmitter | None = None,
    ) -> None:
        if not config.endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint MUST be an absolute https URL")
        if not config.deployment:
            raise ValueError("deployment MUST NOT be empty")
        if config.dim <= 0:
            raise ValueError("dim MUST be > 0")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureOpenAIEmbeddingModelConfig] = config
        self._metering: Final[MeteringEmitter | None] = metering
        # `EmbeddingModel` Protocol declares `dim: int` as a settable
        # attribute; expose it as a plain instance variable rather than a
        # read-only property so structural-typing checks accept the class.
        self.dim: int = config.dim

    async def embed(self, text: str) -> Sequence[float]:
        """Return the embedding vector for ``text``."""
        token = await self._identity.get_token(_COGNITIVE_SCOPE)
        url = (
            self._config.endpoint.rstrip("/")
            + "/openai/deployments/"
            + self._config.deployment
            + "/embeddings"
        )
        response = await self._http.post(
            url,
            params={"api-version": self._config.api_version},
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            },
            json={"input": text},
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if self._metering is not None:
            usage = extract_usage(body)
            if usage is not None:
                await self._metering.emit_safe(usage)
        try:
            vector = body["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Azure OpenAI embeddings response missing data[0].embedding: {body!r}"
            ) from exc
        if not isinstance(vector, list):
            raise RuntimeError("Azure OpenAI embeddings response 'embedding' MUST be a list")
        if len(vector) != self._config.dim:
            raise RuntimeError(
                f"embedding length {len(vector)} != configured dim {self._config.dim}"
            )
        return [float(v) for v in vector]


__all__ = ["AzureOpenAIEmbeddingModel", "AzureOpenAIEmbeddingModelConfig"]
