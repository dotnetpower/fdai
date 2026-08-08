"""AzureOpenAIEmbeddingModel - httpx-based embedding client."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import httpx

from fdai.core.metering.emitter import MeteringEmitter
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.delivery.azure.llm.usage import extract_usage
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity


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

    dim: int = 384
    """Vector dimensionality requested from text-embedding-3 deployments.
    MUST match the pgvector schema contract."""

    timeout_seconds: float = 30.0
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None


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
        target = ModelRequestTarget(
            endpoint=config.endpoint,
            deployment=config.deployment,
            api_style=config.api_style,
            api_version=config.api_version,
            auth_audience=config.auth_audience,
            route_kind=config.route_kind,
            binding_id=config.binding_id,
        )
        if config.dim <= 0:
            raise ValueError("dim MUST be > 0")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureOpenAIEmbeddingModelConfig] = config
        self._metering: Final[MeteringEmitter | None] = metering
        self._target: Final[ModelRequestTarget] = target
        # `EmbeddingModel` Protocol declares `dim: int` as a settable
        # attribute; expose it as a plain instance variable rather than a
        # read-only property so structural-typing checks accept the class.
        self.dim: int = config.dim

    async def embed(self, text: str) -> Sequence[float]:
        """Return the embedding vector for ``text``."""
        token = await self._identity.get_token(self._target.auth_audience)
        request = self._target.operation("embeddings")
        request_body: dict[str, object] = {"input": text, "dimensions": self._config.dim}
        if request.model_body_field is not None:
            request_body["model"] = request.model_body_field
        response = await self._http.post(
            request.url,
            params=request.params,
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        response_body = response.json()
        if self._metering is not None:
            usage = extract_usage(response_body)
            if usage is not None:
                await self._metering.emit_safe(usage)
        try:
            vector = response_body["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Azure OpenAI embeddings response missing data[0].embedding: {response_body!r}"
            ) from exc
        if not isinstance(vector, list):
            raise RuntimeError("Azure OpenAI embeddings response 'embedding' MUST be a list")
        if len(vector) != self._config.dim:
            raise RuntimeError(
                f"embedding length {len(vector)} != configured dim {self._config.dim}"
            )
        return [float(v) for v in vector]


__all__ = ["AzureOpenAIEmbeddingModel", "AzureOpenAIEmbeddingModelConfig"]
