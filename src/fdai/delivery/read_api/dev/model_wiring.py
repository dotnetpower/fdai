"""Narrator and model-settings wiring for the local read API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
            store=InMemoryStateStore(),
            backend=backend,
            web_search_resolver=web_search,
        ),
    )


__all__ = ["LocalModelWiring", "build_local_model_wiring"]
