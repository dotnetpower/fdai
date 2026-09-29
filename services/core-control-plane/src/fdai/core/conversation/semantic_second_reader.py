"""Independent second-reader services offered to the semantic planner.

A second model of another family reads the question without seeing the judgment. It
grounds subtype words by closed choice and quotes every stated constraint, so no single
reading decides a binding or silently narrows a question. Neither service grants
authority or widens a manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .semantic_judgment_coverage import JudgmentCoverageReview
from .semantic_type_grounding import ResourceTypeGrounding


@dataclass(frozen=True, slots=True)
class SemanticSecondReader:
    type_grounding: ResourceTypeGrounding | None = None
    coverage_review: JudgmentCoverageReview | None = None


def planner_arguments(reader: SemanticSecondReader | None) -> dict[str, Any]:
    """Return the planner keywords for an enabled second reader."""

    if reader is None:
        return {}
    return {"type_grounding": reader.type_grounding, "coverage_review": reader.coverage_review}


__all__ = ["SemanticSecondReader", "planner_arguments"]
