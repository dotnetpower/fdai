"""Public provenance projections shared by conversation response paths."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def web_search_summary(view_context: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return public search provenance without echoing untrusted snippet bodies."""

    raw = view_context.get("_web_evidence")
    if not isinstance(raw, Mapping):
        return None
    sources = raw.get("sources")
    safe_sources = (
        [dict(item) for item in sources[:8] if isinstance(item, Mapping)]
        if isinstance(sources, list)
        else []
    )
    summary: dict[str, Any] = {
        "status": str(raw.get("status") or "unavailable"),
        "sources": safe_sources,
    }
    router = raw.get("router")
    if isinstance(router, Mapping):
        summary["router"] = dict(router)
    return summary


__all__ = ["web_search_summary"]
