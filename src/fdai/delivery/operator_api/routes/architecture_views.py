"""Compatibility facade for the core-owned architecture graph projection."""

from fdai.core.views.architecture_graph import (
    DEFAULT_ARCHITECTURE_VIEW_ID,
    SERVICE_TAG_KEYS,
    project_architecture_graph,
)

__all__ = [
    "DEFAULT_ARCHITECTURE_VIEW_ID",
    "SERVICE_TAG_KEYS",
    "project_architecture_graph",
]
