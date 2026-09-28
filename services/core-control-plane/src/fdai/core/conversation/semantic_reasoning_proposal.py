"""Bind model-quoted text to exact utterance spans before form validation.

Models quote the exact words they rely on; they do not count characters. Core
locates each quoted phrase verbatim, as the given occurrence, and replaces it
with a half-open span. A quote that does not occur verbatim fails closed. This
validates the model's output and never infers meaning from the utterance.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .semantic_reasoning_form import SemanticQuestionForm

MAX_QUOTE_CHARS = 512
MAX_OCCURRENCE = 16
_QUOTED_SPAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "occurrence"],
    "properties": {
        "text": {"type": "string", "description": "Exact words copied from the utterance."},
        "occurrence": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_OCCURRENCE,
            "description": "Which verbatim occurrence of text, counting from 1.",
        },
    },
}


@dataclass(frozen=True, slots=True)
class FormResolution:
    form: SemanticQuestionForm | None
    reasons: tuple[str, ...]


def question_form_proposal_schema() -> dict[str, Any]:
    """Return the model-facing schema, with quoted spans in place of offsets."""

    schema = copy.deepcopy(SemanticQuestionForm.model_json_schema())
    definitions = schema.get("$defs", {})
    if "SourceSpan" not in definitions:
        raise ValueError("question form schema has no SourceSpan definition")
    definitions["SourceSpan"] = copy.deepcopy(_QUOTED_SPAN_SCHEMA)
    return schema


def resolve_question_form(raw: Mapping[str, Any], *, utterance: str) -> FormResolution:
    """Return a validated form whose spans point at the quoted utterance text."""

    try:
        payload = copy.deepcopy(dict(raw))
    except (TypeError, ValueError):
        return FormResolution(None, ("form_payload_invalid",))
    failures: list[str] = []
    mentions = payload.get("mentions")
    goals = payload.get("goals")
    if not isinstance(mentions, list) or not isinstance(goals, list):
        return FormResolution(None, ("form_payload_invalid",))
    for mention in mentions:
        if isinstance(mention, dict):
            _bind(mention, "span", utterance, failures, required=True)
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        _bind(goal, "cue", utterance, failures, required=True)
        for key in ("relation", "time"):
            nested = goal.get(key)
            if isinstance(nested, dict):
                _bind(nested, "cue", utterance, failures, required=key == "relation")
    if failures:
        return FormResolution(None, tuple(dict.fromkeys(failures)))
    try:
        return FormResolution(SemanticQuestionForm.model_validate(payload), ())
    except ValidationError as exc:
        fields = sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})
        return FormResolution(None, tuple(f"form_contract_invalid:{field}" for field in fields[:8]))


def locate_quote(text: str, occurrence: int, utterance: str) -> tuple[int, int] | None:
    """Return the span of the given verbatim occurrence of ``text``, if any."""

    if not text or len(text) > MAX_QUOTE_CHARS or not 1 <= occurrence <= MAX_OCCURRENCE:
        return None
    start = -1
    for _ in range(occurrence):
        start = utterance.find(text, start + 1)
        if start < 0:
            return None
    return start, start + len(text)


def _bind(
    container: dict[str, Any],
    key: str,
    utterance: str,
    failures: list[str],
    *,
    required: bool,
) -> None:
    quoted = container.get(key)
    if quoted is None and not required:
        return
    if not isinstance(quoted, Mapping):
        failures.append(f"quote_missing:{key}")
        return
    text = quoted.get("text")
    occurrence = quoted.get("occurrence", 1)
    if not isinstance(text, str) or isinstance(occurrence, bool) or not isinstance(occurrence, int):
        failures.append(f"quote_invalid:{key}")
        return
    span = locate_quote(text, occurrence, utterance)
    if span is None:
        failures.append(f"quote_not_verbatim:{key}")
        return
    container[key] = {"start": span[0], "end": span[1]}


__all__ = [
    "MAX_OCCURRENCE",
    "MAX_QUOTE_CHARS",
    "FormResolution",
    "locate_quote",
    "question_form_proposal_schema",
    "resolve_question_form",
]
