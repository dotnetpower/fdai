"""JSON-safe public metadata for configured conversation backends."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fdai.delivery.operator_api.application.conversation.backend.contracts import (
    ChatBackend,
    ChatBackendMetadata,
    DisabledChatBackend,
)
from fdai.delivery.operator_api.application.conversation.backend.router import (
    LatencyRoutedChatBackend,
)


def describe_backend(backend: ChatBackend) -> dict[str, Any]:
    """Return credential-free backend metadata for route health responses."""

    if isinstance(backend, DisabledChatBackend):
        return {"available": False, "mode": "disabled", "model": None, "endpoint": None}
    if isinstance(backend, LatencyRoutedChatBackend):
        stats = backend.stats()
        chosen = backend.current_pick_name()
        return {
            "available": backend.has_available_candidate(),
            "mode": (
                "azure-ad-routed"
                if backend.has_available_candidate()
                else "azure-ad-routed-unavailable"
            ),
            "model": chosen if backend.has_available_candidate() else None,
            "endpoint": _host_of(backend.endpoints()[0]) if backend.endpoints() else None,
            "router": {
                "chose": chosen,
                "candidates": stats,
                "vision": _vision_description(backend.vision_backend()),
            },
        }
    if isinstance(backend, ChatBackendMetadata):
        return {
            "available": True,
            "mode": backend.mode,
            "model": backend.model,
            "endpoint": _host_of(backend.endpoint),
        }
    return {"available": True, "mode": type(backend).__name__, "model": None, "endpoint": None}


def _vision_description(backend: ChatBackend | None) -> dict[str, Any]:
    if isinstance(backend, LatencyRoutedChatBackend):
        return {
            "available": backend.has_available_candidate(),
            "chose": backend.current_pick_name(),
            "candidates": backend.stats(),
        }
    if isinstance(backend, ChatBackendMetadata):
        return {
            "available": True,
            "chose": backend.model,
            "candidates": [{"deployment": backend.model}],
        }
    return {"available": False, "chose": None, "candidates": []}


def _host_of(url: str) -> str:
    """Extract a public host defensively without exposing credentials."""

    try:
        return urlparse(url).netloc or url
    except ValueError:
        return url
