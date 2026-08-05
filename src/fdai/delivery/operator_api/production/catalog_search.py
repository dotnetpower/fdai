"""Production catalog semantic-search availability and adapter composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from fdai.delivery.azure.llm import AzureOpenAIEmbeddingModel, AzureOpenAIEmbeddingModelConfig
from fdai.delivery.azure.workload_identity import (
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)
from fdai.delivery.catalog_search import (
    PgvectorCatalogSemanticIndex,
    PgvectorCatalogSemanticIndexConfig,
)
from fdai.delivery.operator_api.production.config import ProdOperatorApiConfigError
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.knowledge import Embedder
from fdai.shared.providers.local.secret import EnvSecretProvider

_ENDPOINT_ENV = "FDAI_EMBEDDING_ENDPOINT"
_DEPLOYMENT_ENV = "FDAI_EMBEDDING_DEPLOYMENT"
_DIM_ENV = "FDAI_EMBEDDING_DIM"
_ENABLED_ENV = "FDAI_CATALOG_SEARCH_ENABLED"
_INVENTORY_SEMANTIC_ENABLED_ENV = "FDAI_INVENTORY_SEMANTIC_ENABLED"


@dataclass(frozen=True, slots=True)
class ProductionCatalogSearch:
    index: CatalogSemanticIndex | None
    embedder: Embedder | None = None
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()


def build_production_catalog_search(
    *,
    env: Mapping[str, str],
    dsn: str,
) -> ProductionCatalogSearch:
    enabled = env.get(_ENABLED_ENV, "1").strip().casefold() not in {"0", "false", "no", "off"}
    inventory_semantic_enabled = env.get(
        _INVENTORY_SEMANTIC_ENABLED_ENV,
        "1",
    ).strip().casefold() not in {"0", "false", "no", "off"}
    endpoint = env.get(_ENDPOINT_ENV, "").strip()
    deployment = env.get(_DEPLOYMENT_ENV, "").strip()
    configured = (bool(endpoint), bool(deployment))
    if not enabled and not inventory_semantic_enabled:
        return ProductionCatalogSearch(index=None)
    if configured == (False, False):
        return ProductionCatalogSearch(index=None)
    if configured != (True, True):
        raise ProdOperatorApiConfigError(
            f"{_ENDPOINT_ENV} and {_DEPLOYMENT_ENV} MUST be configured together"
        )
    try:
        dimension = int(env.get(_DIM_ENV, "384"))
    except ValueError as exc:
        raise ProdOperatorApiConfigError(f"{_DIM_ENV} MUST be an integer") from exc
    if dimension != 384:
        raise ProdOperatorApiConfigError(f"{_DIM_ENV} MUST be 384 for catalog_search_document")

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
    )
    identity_endpoint = (
        env.get("IDENTITY_ENDPOINT", "").strip() or env.get("MSI_ENDPOINT", "").strip()
    )
    identity_header = env.get("IDENTITY_HEADER", "").strip() or env.get("MSI_SECRET", "").strip()
    if not identity_endpoint or not identity_header:
        raise ProdOperatorApiConfigError(
            "catalog semantic search requires Managed Identity endpoint and header"
        )
    identity = ManagedIdentityWorkloadIdentity(
        http_client=http_client,
        config=ManagedIdentityWorkloadIdentityConfig(
            endpoint=identity_endpoint,
            header=identity_header,
            client_id=env.get("FDAI_MI_CLIENT_ID", "").strip() or None,
        ),
    )
    embedder = AzureOpenAIEmbeddingModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAIEmbeddingModelConfig(
            endpoint=endpoint,
            deployment=deployment,
            dim=dimension,
        ),
    )
    index = (
        PgvectorCatalogSemanticIndex(
            config=PgvectorCatalogSemanticIndexConfig(
                dsn_secret="catalog-search-dsn",  # noqa: S106 - provider lookup key
                embedding_dim=dimension,
            ),
            embedder=embedder,
            secrets=EnvSecretProvider(env={"catalog-search-dsn": dsn}, prefix=""),
        )
        if enabled
        else None
    )

    async def close_http() -> None:
        await http_client.aclose()

    return ProductionCatalogSearch(
        index=index,
        embedder=embedder,
        shutdown_callbacks=(close_http,),
    )


__all__ = ["ProductionCatalogSearch", "build_production_catalog_search"]
