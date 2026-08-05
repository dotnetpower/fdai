"""Narrator and model-settings wiring for the local Operator API."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.llm import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from fdai.delivery.azure.llm.model_catalog import AzureCliGptModelCatalogReader
from fdai.delivery.operator_api.dev.helpers import (
    build_chat_backend,
    build_chat_web_search,
)
from fdai.delivery.operator_api.routes.model_settings import ModelSettingsService
from fdai.shared.providers.testing.state_store import InMemoryStateStore


@dataclass(frozen=True, slots=True)
class LocalModelWiring:
    backend: Any
    web_search: Any
    settings: ModelSettingsService
    embedder: Any = None
    shutdown_callbacks: tuple[Callable[[], Coroutine[Any, Any, None]], ...] = ()


def build_local_model_wiring(repo_root: Path, *, metering_sink: Any = None) -> LocalModelWiring:
    """Build local narrator providers and their settings service."""
    from fdai.composition import load_pricing_table

    pricing = load_pricing_table(repo_root / "rule-catalog" / "llm-pricing.yaml")
    backend = build_chat_backend(metering_sink, pricing)
    web_search = build_chat_web_search()
    embedder, shutdown_callbacks = _build_local_embedder(repo_root / "resolved-models.json")
    return LocalModelWiring(
        backend=backend,
        web_search=web_search,
        embedder=embedder,
        shutdown_callbacks=shutdown_callbacks,
        settings=ModelSettingsService(
            resolved_models_path=repo_root / "resolved-models.json",
            registry_path=repo_root / "rule-catalog" / "llm-registry.yaml",
            store=InMemoryStateStore(),
            backend=backend,
            web_search_resolver=web_search,
            model_catalog_reader=_build_model_catalog_reader(repo_root),
        ),
    )


def _build_local_embedder(
    resolved_models_path: Path,
) -> tuple[
    AzureOpenAIEmbeddingModel | None,
    tuple[Callable[[], Coroutine[Any, Any, None]], ...],
]:
    enabled = os.environ.get("FDAI_INVENTORY_SEMANTIC_ENABLED", "1").strip().casefold()
    if enabled in {"0", "false", "no", "off"}:
        return None, ()
    endpoint_override = os.environ.get("FDAI_EMBEDDING_ENDPOINT", "").strip()
    deployment_override = os.environ.get("FDAI_EMBEDDING_DEPLOYMENT", "").strip()
    if bool(endpoint_override) != bool(deployment_override):
        raise ValueError(
            "FDAI_EMBEDDING_ENDPOINT and FDAI_EMBEDDING_DEPLOYMENT MUST be configured together"
        )
    try:
        serialized = resolved_models_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, ()
    try:
        resolved = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ValueError("resolved-models.json is invalid") from exc
    capabilities = resolved.get("capabilities") if isinstance(resolved, dict) else None
    embedding_capability = next(
        (
            capability
            for capability in capabilities or ()
            if isinstance(capability, dict)
            and capability.get("name") == "t1.embedding"
            and capability.get("status") in {"resolved", "capacity-reduced"}
        ),
        None,
    )
    if embedding_capability is None:
        return None, ()
    family = embedding_capability.get("family")
    if family not in {"text-embedding-3-small", "text-embedding-3-large"}:
        raise ValueError(
            f"embedding family {family!r} does not support the FDAI 384-dimension contract"
        )
    narrator = resolved.get("narrator")
    narrator_endpoint = narrator.get("endpoint") if isinstance(narrator, dict) else None
    endpoint = endpoint_override or (
        narrator_endpoint if isinstance(narrator_endpoint, str) else ""
    )
    deployment = deployment_override or str(embedding_capability["name"])
    if not endpoint:
        raise ValueError("resolved-models.json lacks an endpoint for local inventory semantics")
    try:
        dimension = int(os.environ.get("FDAI_EMBEDDING_DIM", "384"))
    except ValueError as exc:
        raise ValueError("FDAI_EMBEDDING_DIM MUST be an integer") from exc
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0))
    embedder = AzureOpenAIEmbeddingModel(
        identity=AsyncAzureCliWorkloadIdentity.from_env(),
        http_client=client,
        config=AzureOpenAIEmbeddingModelConfig(
            endpoint=endpoint,
            deployment=deployment,
            dim=dimension,
        ),
    )
    return embedder, (client.aclose,)


def _build_model_catalog_reader(repo_root: Path) -> AzureCliGptModelCatalogReader | None:
    if os.environ.get("FDAI_MODEL_CATALOG_LIVE", "1").strip().casefold() in {"0", "false", "no"}:
        return None
    try:
        resolved = json.loads((repo_root / "resolved-models.json").read_text(encoding="utf-8"))
        narrator = resolved.get("narrator") if isinstance(resolved, dict) else None
        endpoint = narrator.get("endpoint") if isinstance(narrator, dict) else None
        region = resolved.get("region") if isinstance(resolved, dict) else None
        hostname = urlsplit(endpoint).hostname if isinstance(endpoint, str) else None
        account_name = hostname.split(".", 1)[0] if hostname else None
        if not isinstance(region, str) or not region or not account_name:
            return None
        return AzureCliGptModelCatalogReader(region=region, account_name=account_name)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


__all__ = ["LocalModelWiring", "build_local_model_wiring"]
