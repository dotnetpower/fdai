"""Narrator and model-settings wiring for the local read API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fdai.delivery.azure.llm.model_catalog import AzureCliGptModelCatalogReader
from fdai.delivery.read_api.dev.helpers import (
    build_chat_backend,
    build_chat_web_search,
)
from fdai.delivery.read_api.routes.model_settings import ModelSettingsService
from fdai.shared.providers.testing.state_store import InMemoryStateStore


@dataclass(frozen=True, slots=True)
class LocalModelWiring:
    backend: Any
    web_search: Any
    settings: ModelSettingsService


def build_local_model_wiring(repo_root: Path, *, metering_sink: Any = None) -> LocalModelWiring:
    """Build local narrator providers and their settings service."""
    backend = build_chat_backend(metering_sink)
    web_search = build_chat_web_search()
    return LocalModelWiring(
        backend=backend,
        web_search=web_search,
        settings=ModelSettingsService(
            resolved_models_path=repo_root / "resolved-models.json",
            registry_path=repo_root / "rule-catalog" / "llm-registry.yaml",
            store=InMemoryStateStore(),
            backend=backend,
            web_search_resolver=web_search,
            model_catalog_reader=_build_model_catalog_reader(repo_root),
        ),
    )


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
