"""Non-interfering validation of the optional carried question form."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal
from pydantic import ValidationError


def validate_non_interfering_carried_form(raw: Mapping[str, Any]) -> SemanticJudgmentProposal:
    """Validate a judgment while treating an invalid optional form as absent."""

    try:
        return SemanticJudgmentProposal.model_validate(raw)
    except ValidationError as exc:
        if "question_form" not in raw:
            raise
        without_form = dict(raw)
        without_form.pop("question_form", None)
        try:
            return SemanticJudgmentProposal.model_validate(without_form)
        except ValidationError:
            raise exc from None


__all__ = ["validate_non_interfering_carried_form"]
