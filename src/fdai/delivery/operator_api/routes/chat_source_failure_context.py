"""Bounded source-failure receipts reconstructed from verified manifests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

_SCHEMA_VERSION: Final = 1
_MAX_SOURCES: Final = 40
_MAX_TEXT: Final = 1_024


def response_source_failure_context(
    view_context: Mapping[str, Any], *, verification_status: str
) -> dict[str, Any] | None:
    """Project unavailable manifest entries from one verified source read."""

    if verification_status not in {"verified", "corrected"}:
        return None
    tool = view_context.get("_tool_evidence")
    if not isinstance(tool, Mapping) or tool.get("tool") != "describe_read_sources":
        return None
    result = tool.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "matched":
        return None
    raw_sources = result.get("sources")
    if not isinstance(raw_sources, list):
        return None
    sources = tuple(
        source for raw in raw_sources[:_MAX_SOURCES] if (source := _project_source(raw)) is not None
    )
    gaps = tuple(source for source in sources if source["availability"] != "available")
    if not gaps:
        return None
    return {
        "schema_version": _SCHEMA_VERSION,
        "authority": str(tool.get("authority") or "server_read_source_manifest"),
        "truncated": result.get("truncated") is True or len(raw_sources) > len(sources),
        "sources": [dict(source) for source in sources],
        "gaps": [dict(source) for source in gaps],
    }


def parse_source_failure_context(raw: object) -> dict[str, Any] | None:
    """Parse one complete server-owned source-failure replay receipt."""

    if not isinstance(raw, Mapping) or raw.get("schema_version") != _SCHEMA_VERSION:
        return None
    authority = _bounded_text(raw.get("authority"))
    truncated = raw.get("truncated")
    raw_sources = raw.get("sources")
    raw_gaps = raw.get("gaps")
    if (
        authority is None
        or not isinstance(truncated, bool)
        or not isinstance(raw_sources, list)
        or not isinstance(raw_gaps, list)
    ):
        return None
    sources = tuple(_project_source(item) for item in raw_sources[:_MAX_SOURCES])
    gaps = tuple(_project_source(item) for item in raw_gaps[:_MAX_SOURCES])
    if (
        not sources
        or not gaps
        or any(item is None for item in (*sources, *gaps))
        or len(sources) != len(raw_sources)
        or len(gaps) != len(raw_gaps)
    ):
        return None
    projected_sources = tuple(item for item in sources if item is not None)
    projected_gaps = tuple(item for item in gaps if item is not None)
    if any(item["availability"] == "available" for item in projected_gaps):
        return None
    return {
        "schema_version": _SCHEMA_VERSION,
        "authority": authority,
        "truncated": truncated,
        "sources": [dict(item) for item in projected_sources],
        "gaps": [dict(item) for item in projected_gaps],
    }


def source_failure_evidence_refs(raw: object) -> tuple[str, ...]:
    """Return stable refs for every source in a parsed receipt."""

    context = parse_source_failure_context(raw)
    if context is None:
        return ()
    return tuple(
        f"read-source:{source['key']}:{source['source']}:{source['availability']}"
        for source in context["sources"]
        if isinstance(source, Mapping)
    )


def _project_source(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    key = _bounded_text(raw.get("key"))
    source = _bounded_text(raw.get("source"))
    availability = _bounded_text(raw.get("availability"))
    if (
        key is None
        or source is None
        or availability
        not in {
            "available",
            "unavailable",
            "unknown",
        }
    ):
        return None
    projected: dict[str, Any] = {
        "key": key,
        "source": source,
        "availability": availability,
    }
    for field in ("reason", "last_observed_at"):
        value = _bounded_text(raw.get(field))
        if value is not None:
            projected[field] = value
    for field in ("configured", "reachable", "authoritative", "durable", "synthetic"):
        value = raw.get(field)
        if isinstance(value, bool) or value is None:
            projected[field] = value
    return projected


def _bounded_text(raw: object) -> str | None:
    return raw if isinstance(raw, str) and 0 < len(raw) <= _MAX_TEXT else None


__all__ = [
    "parse_source_failure_context",
    "response_source_failure_context",
    "source_failure_evidence_refs",
]
