"""Independent, blind extraction of the constraints a question states.

Admission bounds the proposer but cannot check its judgment: a word it labels context,
a cue stretched over a constraint, or a constraint it never saw all pass deterministic
checks, and a reviewer shown the proposal tends to repeat its reading. A second,
independent model call therefore reads only the question and extracts every constraint
with a closed role. Core never interprets the question; it compares the two independent
outputs structurally. Every letter and digit of each extracted constraint must lie in a
span that states meaning, never only in a goal cue or context, and a named thing must
overlap a mention. Roles beyond that stay advisory, because two independent readers may
fairly disagree on whether a word restricts or relates. A malformed, empty, unlocated,
or unavailable extraction releases nothing.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .semantic_reasoning_form import GoalOperation, SemanticQuestionForm, SourceSpan
from .semantic_reasoning_proposal import MAX_OCCURRENCE, locate_quote

MAX_EXTRACTED_CONSTRAINTS = 24
MAX_REVIEW_REASONS = 8
_QUOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "occurrence"],
    "properties": {
        "text": {"type": "string", "description": "Exact words copied from the question."},
        "occurrence": {"type": "integer", "minimum": 1, "maximum": MAX_OCCURRENCE},
    },
}


class ConstraintRole(StrEnum):
    NAMES = "names"
    RESTRICTS = "restricts"
    RELATES = "relates"
    TIMES = "times"
    GROUPS = "groups"
    MEASURES = "measures"
    ORDERS = "orders"
    COMPARES = "compares"
    NEGATES = "negates"
    SUPPOSES = "supposes"
    ASKS = "asks"


_RANKING = frozenset({GoalOperation.RANK, GoalOperation.AGGREGATE})
_COMPARISON = frozenset(
    {GoalOperation.COMPARE_WINDOWS, GoalOperation.COMPARE_ENTITIES, GoalOperation.DIFF_VERSIONS}
)


class _ExtractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExtractedConstraint(_ExtractionModel):
    quote: SourceSpan
    role: ConstraintRole


class ConstraintExtraction(_ExtractionModel):
    """Every constraint the question states, each with its exact words and closed role."""

    constraints: Annotated[
        tuple[ExtractedConstraint, ...], Field(max_length=MAX_EXTRACTED_CONSTRAINTS)
    ]


@dataclass(frozen=True, slots=True)
class FormReview:
    """Typed review outcome; only ``faithful`` lets a compilation be released."""

    outcome: Literal["faithful", "unfaithful", "invalid", "unavailable"]
    reasons: tuple[str, ...] = ()

    @property
    def faithful(self) -> bool:
        return self.outcome == "faithful"


def extraction_schema() -> dict[str, Any]:
    """Return the extractor-facing schema, with quoted spans in place of offsets."""

    schema = copy.deepcopy(ConstraintExtraction.model_json_schema())
    definitions = schema.get("$defs", {})
    if "SourceSpan" not in definitions:
        raise ValueError("constraint extraction schema has no SourceSpan definition")
    definitions["SourceSpan"] = copy.deepcopy(_QUOTE_SCHEMA)
    return schema


def review_forms(
    forms: Sequence[SemanticQuestionForm],
    raw: Mapping[str, Any] | None,
    *,
    utterance: str,
) -> FormReview:
    """Compare the admitted forms with the blind extraction and return the verdict."""

    if raw is None:
        return FormReview("unavailable", ("review_unavailable",))
    extraction = resolve_extraction(raw, utterance)
    if extraction is None:
        return FormReview("invalid", ("review_invalid",))
    uncovered = uncovered_constraints(forms, extraction, utterance)
    if uncovered:
        reasons = (
            f"review_uncovered:{item.role.value}:{item.quote.start}-{item.quote.end}"
            for item in uncovered
        )
        return FormReview("unfaithful", tuple(dict.fromkeys(reasons))[:MAX_REVIEW_REASONS])
    return FormReview("faithful")


def resolve_extraction(raw: Mapping[str, Any], utterance: str) -> ConstraintExtraction | None:
    """Return the located extraction, or None when it cannot serve as a review."""

    try:
        payload = copy.deepcopy(dict(raw))
    except (TypeError, ValueError):
        return None
    constraints = payload.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        # Every question states at least what it asks, so an empty extraction is no review.
        return None
    for item in constraints:
        if not isinstance(item, dict):
            return None
        span = _locate(item.get("quote"), utterance)
        if span is None:
            return None
        item["quote"] = {"start": span[0], "end": span[1]}
    try:
        return ConstraintExtraction.model_validate(payload)
    except ValidationError:
        return None


def uncovered_constraints(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction, utterance: str
) -> tuple[ExtractedConstraint, ...]:
    """Return each extracted constraint the admitted forms do not state."""

    semantic, mentions = _semantic_spans(forms)
    # A hypothetical premise, such as if it fails, is what an impact goal states.
    supposing = any(
        goal.effective_operation is GoalOperation.IMPACT for form in forms for goal in form.goals
    )
    return tuple(
        item
        for item in extraction.constraints
        if item.role is not ConstraintRole.ASKS
        and not (item.role is ConstraintRole.SUPPOSES and supposing)
        and not _stated(item, semantic, mentions, utterance)
    )


def describe_uncovered(item: ExtractedConstraint, utterance: str) -> str:
    """Render one uncovered constraint as a repair violation the proposer can act on."""

    quote = _quote(item.quote.start, item.quote.end, utterance)
    return (
        f'review_uncovered: the words "{quote["text"]}" at occurrence {quote["occurrence"]} '
        f"state a {item.role.value} constraint that no mention, filter, relation, time, "
        "measure, or unsupported constraint states"
    )


def quoted_form(form: SemanticQuestionForm, utterance: str) -> dict[str, Any]:
    """Render a form as the model writes it, with every span as an exact quote."""

    quoted: dict[str, Any] = _quoted(form.model_dump(mode="json"), utterance)
    return quoted


def _semantic_spans(
    forms: Sequence[SemanticQuestionForm],
) -> tuple[list[SourceSpan], list[SourceSpan]]:
    """Return every span that states meaning, and the mention spans among them."""

    mentions = [mention.span for form in forms for mention in form.mentions]
    semantic = list(mentions)
    for form in forms:
        semantic.extend(form.unsupported_constraints)
        for goal in form.goals:
            if goal.effective_operation in _RANKING | _COMPARISON:
                semantic.append(goal.cue)
            semantic.extend(item.cue for item in goal.filters if item.cue is not None)
            if goal.relation is not None:
                semantic.append(goal.relation.cue)
            if goal.time.cue is not None:
                semantic.append(goal.time.cue)
            if goal.measure is not None and goal.measure.cue is not None:
                semantic.append(goal.measure.cue)
    return semantic, mentions


def _stated(
    item: ExtractedConstraint,
    semantic: list[SourceSpan],
    mentions: list[SourceSpan],
    utterance: str,
) -> bool:
    start, end = item.quote.start, item.quote.end
    if item.role is ConstraintRole.NAMES and not any(
        span.start < end and start < span.end for span in mentions
    ):
        return False
    # Every letter and digit needs a span that states meaning; context or a goal cue never does.
    return all(
        any(span.start <= index < span.end for span in semantic)
        for index in range(start, min(end, len(utterance)))
        if utterance[index].isalnum()
    )


def _quoted(value: Any, utterance: str) -> Any:
    if isinstance(value, dict):
        if set(value) == {"start", "end"} and all(type(item) is int for item in value.values()):
            return _quote(value["start"], value["end"], utterance)
        return {key: _quoted(item, utterance) for key, item in value.items()}
    if isinstance(value, list):
        return [_quoted(item, utterance) for item in value]
    return value


def _quote(start: int, end: int, utterance: str) -> dict[str, Any]:
    text = utterance[start:end]
    occurrence = 0
    position = -1
    while (position := utterance.find(text, position + 1)) != -1 and position <= start:
        occurrence += 1
    return {"text": text, "occurrence": max(occurrence, 1)}


def _locate(quote: object, utterance: str) -> tuple[int, int] | None:
    if not isinstance(quote, Mapping):
        return None
    text = quote.get("text")
    occurrence = quote.get("occurrence", 1)
    if not isinstance(text, str) or type(occurrence) is not int:
        return None
    return locate_quote(text, occurrence, utterance)


__all__ = [
    "MAX_EXTRACTED_CONSTRAINTS",
    "ConstraintExtraction",
    "ConstraintRole",
    "ExtractedConstraint",
    "FormReview",
    "describe_uncovered",
    "extraction_schema",
    "quoted_form",
    "resolve_extraction",
    "review_forms",
    "uncovered_constraints",
]
