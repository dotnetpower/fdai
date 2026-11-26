"""Runtime binding for Mimir operational catalog reviews."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.agents._framework.base import Agent
from fdai.agents.mimir import Mimir
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogReviewPublisher,
)


@dataclass(frozen=True, slots=True)
class CatalogReviewBindings:
    """Dependencies required to compile and optionally publish review packages."""

    compiler: CatalogCandidateCompiler
    publisher: CatalogReviewPublisher | None = None


def bind_catalog_review(
    agents: dict[str, Agent],
    bindings: CatalogReviewBindings | None,
) -> None:
    """Replace the default Mimir only when O3 bindings are configured."""
    if bindings is None:
        return
    agents["Mimir"] = Mimir(
        catalog_candidate_compiler=bindings.compiler,
        catalog_review_publisher=bindings.publisher,
    )


__all__ = ["CatalogReviewBindings", "bind_catalog_review"]
