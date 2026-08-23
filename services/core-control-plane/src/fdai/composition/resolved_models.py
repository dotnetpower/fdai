"""Resolved-model loading and capability helpers for composition binders."""

from __future__ import annotations

from pathlib import Path

from ..rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from ._helpers import LlmBindingsUnavailableError


def _load_resolved_models(path_or_ref: str) -> ResolvedModels:
    """Load resolved models from inline JSON or a mounted filesystem path."""
    stripped = path_or_ref.strip()
    if stripped.startswith("{"):
        return ResolvedModels.from_json(stripped)
    path = Path(path_or_ref)
    if not path.exists():
        raise LlmBindingsUnavailableError(
            f"resolved-models.json not found at {path_or_ref!r}. "
            "Run the bootstrap resolver first (llm_resolver_cli)."
        )
    return ResolvedModels.from_json(path.read_text(encoding="utf-8"))


def _capability(resolved: ResolvedModels, name: str) -> ResolvedCapability | None:
    """Return a resolved capability only when it is bindable."""
    for capability in resolved.capabilities:
        if capability.name != name:
            continue
        if capability.status is CapabilityStatus.HIL_ONLY:
            return None
        return capability
    return None


def _default_dim_for_family(family: str) -> int:
    """Return the fixed pgvector dimension for supported embedding families."""
    if family not in {"text-embedding-3-small", "text-embedding-3-large"}:
        raise LlmBindingsUnavailableError(
            f"embedding family {family!r} does not support the FDAI 384-dimension contract"
        )
    return 384
