"""Independent second-reader services offered to the semantic planner.

A second model of another family reads the question without seeing the judgment. It
grounds subtype words by closed choice and quotes every stated constraint, so no single
reading decides a binding or silently narrows a question. In the local profile the same
reader may also carry the question-form path that answers a released compilation. None
of these services grants authority or widens a manifest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway

from .semantic_compiled_answers import CompiledAnswerPath
from .semantic_judgment_coverage import JudgmentCoverageReview
from .semantic_type_grounding import ResourceTypeGrounding

CompiledAnswerFactory = Callable[
    [SecuredObjectSetQueryGateway, str, Callable[[], datetime]], CompiledAnswerPath
]


@dataclass(frozen=True, slots=True)
class SemanticSecondReader:
    type_grounding: ResourceTypeGrounding | None = None
    coverage_review: JudgmentCoverageReview | None = None
    compiled_answers: CompiledAnswerFactory | None = None


def planner_arguments(
    reader: SemanticSecondReader | None,
    gateway: SecuredObjectSetQueryGateway | None = None,
    purpose: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Return the planner keywords for an enabled second reader."""

    if reader is None:
        return {}
    arguments: dict[str, Any] = {
        "type_grounding": reader.type_grounding,
        "coverage_review": reader.coverage_review,
    }
    if (
        reader.compiled_answers is not None
        and gateway is not None
        and purpose is not None
        and clock is not None
    ):
        arguments["compiled_answers"] = reader.compiled_answers(gateway, purpose, clock)
    return arguments


__all__ = ["CompiledAnswerFactory", "SemanticSecondReader", "planner_arguments"]
