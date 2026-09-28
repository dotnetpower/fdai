"""Input bounds applied before any semantic-judgment model call."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import canonical_json

_MAX_CONTEXT_ITEMS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_CAPABILITIES = 512
_MAX_CAPABILITY_BYTES = 524_288


def bounded_context(context: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    total = 0
    for item in tuple(context)[-_MAX_CONTEXT_ITEMS:]:
        if not isinstance(item, str):
            raise TypeError("semantic judgment context MUST contain strings")
        total += len(item)
        if total > _MAX_CONTEXT_CHARS:
            raise ValueError("semantic judgment context exceeds its bound")
        selected.append(item)
    return tuple(selected)


def bounded_capabilities(
    capabilities: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if len(capabilities) > _MAX_CAPABILITIES:
        raise ValueError("semantic judgment capabilities exceed their count bound")
    selected = tuple(dict(item) for item in capabilities)
    if len(canonical_json(list(selected)).encode()) > _MAX_CAPABILITY_BYTES:
        raise ValueError("semantic judgment capabilities exceed their byte bound")
    return selected


def bounded_direct_response_profile(
    profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    selected = dict(profile or {})
    encoded = canonical_json(selected).encode()
    if len(encoded) > 16_384:
        raise ValueError("semantic direct response profile exceeds its byte bound")
    return selected


__all__ = ["bounded_capabilities", "bounded_context", "bounded_direct_response_profile"]
