"""Independent, blind extraction of the constraints a question states.

Admission bounds the proposer but cannot check its judgment: a word it labels context,
a cue stretched over a constraint, or a constraint it never saw all pass deterministic
checks, and a reviewer shown the proposal tends to repeat its reading. A second,
independent model call therefore reads only the question and extracts every constraint
with a closed role. Core never interprets the question; it compares the two independent
outputs structurally. Every letter and digit of each extracted constraint must lie in a
span that states meaning, never only in a goal cue or context, and a named thing must
overlap a mention. One mention binds one concept or one identity, so a mention may not
hold a restriction the extractor found beside another constraint it found: binding would
keep one and silently drop the other. A literal operand, the mention a name-fragment
filter reads, is used verbatim, so its quote must equal a literal the extractor quoted on
its own; no single reader decides where a literal ends. No closed field states an
exclusion such as not or only, and only a ranking or comparison goal states an order or a
comparison, so those roles need an unsupported constraint or that goal's cue; a cue,
context, or particle that covers one would drop it. Roles beyond that stay advisory, because two
independent readers may fairly disagree on whether a word restricts or relates. A
malformed, empty, unlocated, or unavailable extraction releases nothing.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .semantic_reasoning_form import (
    FilterRole,
    FormGoal,
    GoalLevel,
    GoalOperation,
    MeasureKind,
    MentionDomain,
    MentionForm,
    RelationSense,
    SemanticQuestionForm,
    SourceSpan,
    SubjectRole,
)
from .semantic_reasoning_proposal import MAX_OCCURRENCE, RequestKind, locate_quote

MAX_EXTRACTED_CONSTRAINTS = 24
# Domains whose mention binds one declaration name, so it can hold no second named thing.
_DECLARATION_NAMES = frozenset({MentionDomain.DECLARATION_KIND, MentionDomain.OBJECT_TYPE})
MAX_EXTRACTED_LITERALS = 8
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
    QUANTIFIES = "quantifies"
    ASKS = "asks"
    # A word that only restates that a schema thing is declared or has declarations, such as
    # declared, defined, or have in which LinkTypes Workload has.
    DECLARES = "declares"


_RANKING = frozenset({GoalOperation.RANK, GoalOperation.AGGREGATE})
_ISOLATED_ROLES = frozenset(
    {
        ConstraintRole.RESTRICTS,
        ConstraintRole.NEGATES,
        ConstraintRole.COMPARES,
        ConstraintRole.ORDERS,
        ConstraintRole.TIMES,
    }
)
_COMPARISON = frozenset(
    {GoalOperation.COMPARE_WINDOWS, GoalOperation.COMPARE_ENTITIES, GoalOperation.DIFF_VERSIONS}
)
_UNSTATED_ROLES = frozenset({ConstraintRole.ASKS, ConstraintRole.QUANTIFIES})
_UNEXPRESSIBLE: dict[ConstraintRole, frozenset[GoalOperation]] = {
    ConstraintRole.NEGATES: frozenset(),
    ConstraintRole.COMPARES: _RANKING | _COMPARISON,
    ConstraintRole.ORDERS: _RANKING,
}


class AnswerKind(StrEnum):
    """The closed kind of answer a question asks for, named by the blind reader."""

    LIST = "list"
    COUNT = "count"
    STATE = "state"
    VALUE = "value"
    LOCATION = "location"
    RELATION = "relation"
    HISTORY = "history"
    CAUSE = "cause"
    SCHEMA = "schema"
    OTHER = "other"


# Operations whose answer kind the review does not judge, such as a comparison or a draft.
_UNJUDGED_OPERATIONS = frozenset(
    {
        GoalOperation.COMPARE_WINDOWS,
        GoalOperation.COMPARE_ENTITIES,
        GoalOperation.DIFF_VERSIONS,
        GoalOperation.VERIFY_EVIDENCE,
        GoalOperation.DRAFT_ACTION,
    }
)
_STATE_MEASURES = frozenset({MeasureKind.STATE, MeasureKind.HEALTH})
_VALUE_MEASURES = frozenset(
    {MeasureKind.METRIC, MeasureKind.COST, MeasureKind.FORECAST, MeasureKind.PROPERTY}
)


class _ExtractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExtractedConstraint(_ExtractionModel):
    quote: SourceSpan
    role: ConstraintRole


class ConstraintExtraction(_ExtractionModel):
    """Every constraint the question states, and every literal value it gives exactly.

    ``literals`` defaults to empty only so an older payload still parses; an empty list
    never excuses a literal operand, which then has no agreeing quote and is held.
    """

    constraints: Annotated[
        tuple[ExtractedConstraint, ...], Field(max_length=MAX_EXTRACTED_CONSTRAINTS)
    ]
    literals: Annotated[tuple[SourceSpan, ...], Field(max_length=MAX_EXTRACTED_LITERALS)] = ()
    # The kind of answer asked; an older payload without it, or null, is not judged.
    answer_kind: AnswerKind | None = None
    request_kind: RequestKind | None = None


@dataclass(frozen=True, slots=True)
class FormReview:
    """Typed review outcome; only ``faithful`` lets a compilation be released."""

    outcome: Literal["faithful", "unfaithful", "invalid", "unavailable"]
    reasons: tuple[str, ...] = ()
    primary_read: bool = False

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
    # Strict structured output requires every property, so the extractor always answers.
    schema["required"] = sorted(
        {*schema.get("required", ()), "literals", "answer_kind", "request_kind"}
    )
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
    extraction = _resolved(raw, utterance)
    if isinstance(extraction, str):
        return FormReview("invalid", ("review_invalid", f"review_invalid:{extraction}"))
    uncovered = uncovered_constraints(forms, extraction, utterance)
    unacknowledged = unacknowledged_constraints(forms, extraction, utterance)
    merged = merged_constraints(forms, extraction)
    differing = literal_disagreements(forms, extraction)
    other_kind = answer_kind_unanswered(forms, extraction)
    if uncovered or unacknowledged or merged or differing or other_kind is not None:
        reasons = (
            *(() if other_kind is None else (f"review_answer_kind:{other_kind.value}",)),
            *(
                f"review_uncovered:{item.role.value}:{item.quote.start}-{item.quote.end}"
                for item in uncovered
            ),
            *(
                f"review_unexpressible:{item.role.value}:{item.quote.start}-{item.quote.end}"
                for item in unacknowledged
            ),
            *(f"review_merged:{item.quote.start}-{item.quote.end}" for item in merged),
            *(f"review_literal_differs:{item.start}-{item.end}" for item in differing),
        )
        return FormReview("unfaithful", tuple(dict.fromkeys(reasons))[:MAX_REVIEW_REASONS])
    return FormReview("faithful", primary_read=extraction.request_kind == "direct_read")


def answer_kind_unanswered(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction
) -> AnswerKind | None:
    """Return the answer kind the blind reader named when no goal answers that kind.

    A form can be faithful to every quoted constraint and still answer another question,
    such as a current-state lookup for a question asking where a subnet is located. Only
    closed values decide this: the reader's kind and each goal's operation, measure,
    level, filters, and relation roles.
    """

    kind = extraction.answer_kind
    if kind is None or kind is AnswerKind.OTHER:
        return None
    goals = [goal for form in forms for goal in form.goals]
    if not goals or any(
        goal.effective_operation in _UNJUDGED_OPERATIONS or kind in answer_kinds(goal)
        for goal in goals
    ):
        return None
    return kind


def answer_kinds(goal: FormGoal) -> frozenset[AnswerKind]:
    """Return the closed answer kinds one goal's typed reading can answer."""

    if goal.level is GoalLevel.SCHEMA or goal.operation is GoalOperation.DESCRIBE_SCHEMA:
        return frozenset(
            {AnswerKind.SCHEMA, AnswerKind.LIST, AnswerKind.COUNT, AnswerKind.RELATION}
        )
    operation = goal.effective_operation
    measure = goal.measure.kind if goal.measure is not None else None
    if operation is GoalOperation.COUNT or (
        operation is GoalOperation.AGGREGATE and measure is MeasureKind.COUNT
    ):
        return frozenset({AnswerKind.COUNT})
    if operation is GoalOperation.AGGREGATE:
        return frozenset({AnswerKind.COUNT, AnswerKind.VALUE})
    if operation in {GoalOperation.SELECT, GoalOperation.RANK}:
        kinds = {AnswerKind.LIST, *_relation_kinds(goal)}
        # A list filtered by a state answers whether its members are in that state.
        if any(item.role in {FilterRole.STATE, FilterRole.HEALTH} for item in goal.filters):
            kinds.add(AnswerKind.STATE)
        # A metric threshold or a metric order reads each member's measured value, and a
        # threshold also answers whether members cross it.
        if any(item.role is FilterRole.METRIC for item in goal.filters):
            kinds.update({AnswerKind.STATE, AnswerKind.VALUE})
        if operation is GoalOperation.RANK and measure is MeasureKind.METRIC:
            kinds.add(AnswerKind.VALUE)
        return frozenset(kinds)
    if operation in {GoalOperation.TRAVERSE, GoalOperation.PATH, GoalOperation.IMPACT}:
        return frozenset({AnswerKind.LIST, AnswerKind.RELATION, *_relation_kinds(goal)})
    if operation is GoalOperation.LOOKUP:
        if measure in _STATE_MEASURES:
            return frozenset({AnswerKind.STATE})
        if measure in _VALUE_MEASURES:
            return frozenset({AnswerKind.VALUE})
        return frozenset({AnswerKind.STATE, AnswerKind.VALUE})
    if operation is GoalOperation.HISTORY:
        return frozenset({AnswerKind.HISTORY, AnswerKind.LIST})
    if operation is GoalOperation.EXPLAIN_CAUSE:
        return frozenset({AnswerKind.CAUSE})
    if operation is GoalOperation.DIAGNOSE:
        return frozenset({AnswerKind.CAUSE, AnswerKind.STATE})
    return frozenset(AnswerKind)


def _relation_kinds(goal: FormGoal) -> frozenset[AnswerKind]:
    """Return the kinds a goal's relation answers; a selection with one reads the relation.

    The container a thing sits in is where it is located, as in which group contains it.
    """

    relation = goal.relation
    if relation is None:
        return frozenset()
    located = relation.result_role is SubjectRole.CONTAINER
    if relation.sense is RelationSense.CONTAINMENT and located:
        return frozenset({AnswerKind.RELATION, AnswerKind.LOCATION})
    return frozenset({AnswerKind.RELATION})


def resolve_extraction(raw: Mapping[str, Any], utterance: str) -> ConstraintExtraction | None:
    """Return the located extraction, or None when it cannot serve as a review."""

    resolved = _resolved(raw, utterance)
    return None if isinstance(resolved, str) else resolved


def _resolved(raw: Mapping[str, Any], utterance: str) -> ConstraintExtraction | str:
    """Return the located extraction, or the typed reason it cannot serve as a review."""

    try:
        payload = copy.deepcopy(dict(raw))
    except (TypeError, ValueError):
        return "payload"
    constraints = payload.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        # Every question states at least what it asks, so an empty extraction is no review.
        return "constraints_empty"
    for item in constraints:
        if not isinstance(item, dict):
            return "constraint_shape"
        span = _locate(item.get("quote"), utterance)
        if span is None:
            return "constraint_quote_unlocated"
        item["quote"] = {"start": span[0], "end": span[1]}
    literals = payload.get("literals", [])
    if not isinstance(literals, list):
        return "literal_shape"
    located_literals = []
    for quote in literals:
        span = _locate(quote, utterance)
        if span is None:
            return "literal_quote_unlocated"
        located_literals.append({"start": span[0], "end": span[1]})
    payload["literals"] = located_literals
    try:
        return ConstraintExtraction.model_validate(payload)
    except ValidationError:
        return "schema"


def uncovered_constraints(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction, utterance: str
) -> tuple[ExtractedConstraint, ...]:
    """Return each extracted constraint the admitted forms do not state."""

    semantic, mentions = _semantic_spans(forms)
    # A particle attached after a mention in the same word, such as the case ending of a
    # Korean name, belongs to that mention; only whitespace delimits the word.
    suffixes = [suffix for span in mentions if (suffix := _attached(span, utterance)) is not None]
    # A hypothetical premise, such as if it fails, is what an impact goal states.
    supposing = any(
        goal.effective_operation is GoalOperation.IMPACT for form in forms for goal in form.goals
    )
    unstated = _unstated_roles(forms)
    uncovered: list[ExtractedConstraint] = []
    for item in extraction.constraints:
        # A request word and a word meaning all or every state no restriction to cover.
        if item.role in unstated or (item.role is ConstraintRole.SUPPOSES and supposing):
            continue
        # A restriction the extractor isolated inside such a particle, such as only or
        # from, narrows the answer, so the mention it rides on never states it.
        isolated = item.role in _ISOLATED_ROLES and any(
            span.start <= item.quote.start and item.quote.end <= span.end for span in suffixes
        )
        spans = semantic if isolated else [*semantic, *suffixes]
        if not _stated(item, spans, mentions, utterance):
            uncovered.append(item)
    return tuple(uncovered)


def _typed_expressions(
    forms: Sequence[SemanticQuestionForm], role: ConstraintRole
) -> list[SourceSpan]:
    """Return the spans of typed fields that state a comparison or an order.

    A metric filter's comparison states a threshold, and a stated order states how its
    goal ranks; both are closed fields, so their quoted words acknowledge the constraint.
    """

    spans: list[SourceSpan] = []
    for form in forms:
        for goal in form.goals:
            if role is ConstraintRole.COMPARES:
                for item in goal.filters:
                    if item.comparison is not None:
                        spans.append(item.comparison.comparator_span)
                        spans.append(item.comparison.value_span)
                        if item.comparison.unit_span is not None:
                            spans.append(item.comparison.unit_span)
            order = goal.measure.order if goal.measure is not None else None
            if role is ConstraintRole.ORDERS and order is not None:
                spans.extend(span for span in (order.cue, order.limit_span) if span is not None)
    return spans


def unacknowledged_constraints(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction, utterance: str
) -> tuple[ExtractedConstraint, ...]:
    """Return each exclusion, comparison, or order the forms state only by absorbing it.

    No closed field expresses an exclusion, and only a ranking or comparison goal
    expresses an order or a comparison, so such a constraint must reach an unsupported
    constraint or that goal's cue. Characters inside a mention, such as the name an
    exclusion follows, need no acknowledgment.
    """

    mentions = [mention.span for form in forms for mention in form.mentions]
    unacknowledged: list[ExtractedConstraint] = []
    for item in extraction.constraints:
        operations = _UNEXPRESSIBLE.get(item.role)
        if operations is None:
            continue
        allowed = [span for form in forms for span in form.unsupported_constraints]
        allowed.extend(
            goal.cue
            for form in forms
            for goal in form.goals
            if goal.effective_operation in operations
        )
        allowed.extend(_typed_expressions(forms, item.role))
        stated = [
            index
            for index in range(item.quote.start, min(item.quote.end, len(utterance)))
            if utterance[index].isalnum()
            and not any(span.start <= index < span.end for span in mentions)
        ]
        if stated and not any(
            span.start <= index < span.end for index in stated for span in allowed
        ):
            unacknowledged.append(item)
    return tuple(unacknowledged)


def describe_unexpressible(item: ExtractedConstraint, utterance: str) -> str:
    """Render one absorbed exclusion, comparison, or order as a repair violation."""

    quote = _quote(item.quote.start, item.quote.end, utterance)
    return (
        f'review_unexpressible: the words "{quote["text"]}" at occurrence {quote["occurrence"]} '
        f"state a {item.role.value} constraint that no closed field expresses, so also add "
        "them to unsupported_constraints and keep every cue and mention as it is"
    )


def merged_constraints(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction
) -> tuple[ExtractedConstraint, ...]:
    """Return each extracted constraint that one mention would drop when it binds.

    A product word inside a mention for the kind of thing it restricts, such as AKS in
    one mention for AKS ObjectTypes, would bind as one concept and lose the restriction.
    A declaration kind or ObjectType is one closed name, so such a mention that holds
    another disjoint constraint binds one name and drops or confuses the other: Workload
    ObjectType bound as a declaration kind lists every ObjectType, and Resource ObjectType
    was bound to the ResourceType ObjectType. The form states the kind word as its own
    declaration-kind mention instead. Only the extractor's closed roles, the mention's
    domain, and the exact spans decide this; Core never reads the words. Overlapping
    quotes restate one constraint, so only disjoint ones count.
    """

    found: dict[tuple[int, int], ExtractedConstraint] = {}
    for held, _parts in _merging(forms, extraction).values():
        for item in held:
            found.setdefault((item.quote.start, item.quote.end), item)
    return tuple(found.values())


def merged_mentions(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction
) -> dict[str, tuple[ExtractedConstraint, ...]]:
    """Return, per merging mention id, the disjoint extracted constraints it holds.

    The mapping keeps the mention order of the forms and each mention's parts in their
    question order, so a repair can name exactly where the mention should split: every
    constraint it drops and every disjoint constraint beside one.
    """

    return {mention_id: parts for mention_id, (_held, parts) in _merging(forms, extraction).items()}


def _merging(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction
) -> dict[str, tuple[tuple[ExtractedConstraint, ...], tuple[ExtractedConstraint, ...]]]:
    """Return, per merging mention id, the constraints it drops and the parts it holds."""

    unstated = _unstated_roles(forms)
    stated = [item for item in extraction.constraints if item.role not in unstated]
    merged: dict[str, tuple[tuple[ExtractedConstraint, ...], tuple[ExtractedConstraint, ...]]] = {}
    # A reference's position words, such as second in the second one, are its typed
    # position, not a restriction a concept binding could drop.
    grounded = (
        mention
        for form in forms
        for mention in form.mentions
        if mention.form not in {MentionForm.ORDINAL, MentionForm.ANAPHOR}
    )
    for mention in grounded:
        inside = [
            item
            for item in stated
            if mention.span.start <= item.quote.start and item.quote.end <= mention.span.end
        ]
        kind = mention.domain in _DECLARATION_NAMES
        held = {
            (item.quote.start, item.quote.end): item
            for item in inside
            if (kind or item.role is ConstraintRole.RESTRICTS)
            and any(
                other.quote.end <= item.quote.start or item.quote.end <= other.quote.start
                for other in inside
            )
        }
        if held:
            # Every disjoint constraint the mention holds is a part the split must keep apart.
            parts = {
                (item.quote.start, item.quote.end): item
                for item in inside
                if any(
                    other.quote.end <= item.quote.start or item.quote.end <= other.quote.start
                    for other in held.values()
                )
                or (item.quote.start, item.quote.end) in held
            }
            merged[mention.id] = (
                tuple(held.values()),
                tuple(parts[key] for key in sorted(parts)),
            )
    return merged


def _unstated_roles(forms: Sequence[SemanticQuestionForm]) -> frozenset[ConstraintRole]:
    """Return the roles no span needs to state for these forms.

    A word the independent reader says only restates declaration states nothing a schema
    reading must cover, because the schema level already reads declarations. Beside an
    instance goal the same word may relate or restrict, so it is then held to coverage.
    """

    goals = [goal for form in forms for goal in form.goals]
    if goals and all(goal.level is GoalLevel.SCHEMA for goal in goals):
        return _UNSTATED_ROLES | {ConstraintRole.DECLARES}
    return _UNSTATED_ROLES


def describe_merged(
    mention_id: str,
    span: SourceSpan,
    parts: Sequence[ExtractedConstraint],
    utterance: str,
) -> str:
    """Render one merging mention as a repair violation naming the parts to keep apart.

    The parts are the independent reader's disjoint quotes; Core never reads the words.
    """

    quote = _quote(span.start, span.end, utterance)
    named = "; ".join(
        f'"{_quote(item.quote.start, item.quote.end, utterance)["text"]}" ({item.role.value})'
        for item in parts
    )
    return (
        f'review_merged: mention {mention_id} quotes "{quote["text"]}" at occurrence '
        f"{quote['occurrence']}, which holds separate constraints an independent reading "
        f"found: {named}. Replace it with one mention for each of them, cite each where the "
        "goal reads it, and keep every other mention, goal, and cue as it is"
    )


def literal_operands(forms: Sequence[SemanticQuestionForm]) -> frozenset[tuple[int, str]]:
    """Return each mention whose quote is used verbatim, by form index and mention id."""

    return frozenset(
        (index, mention_id)
        for index, form in enumerate(forms)
        for mention_id in form.literal_mentions()
    )


def literal_disagreements(
    forms: Sequence[SemanticQuestionForm], extraction: ConstraintExtraction
) -> tuple[SourceSpan, ...]:
    """Return each literal operand whose quote no extracted literal matches exactly."""

    extracted = {(item.start, item.end) for item in extraction.literals}
    differing: dict[tuple[int, int], SourceSpan] = {}
    for index, mention_id in sorted(literal_operands(forms)):
        span = forms[index].mention(mention_id).span
        if (span.start, span.end) not in extracted:
            differing.setdefault((span.start, span.end), span)
    return tuple(differing.values())


def describe_uncovered(
    item: ExtractedConstraint,
    utterance: str,
    forms: Sequence[SemanticQuestionForm] = (),
) -> str:
    """Render one uncovered constraint as a repair violation the proposer can act on.

    When a mention already quotes part of the constraint's words, the violation names
    that mention, so the proposer decides whether the rest belongs to the same thing or
    states something else; Core never decides that from the words. A value mention's
    quote is a literal operand that a review repair may not change, so the violation
    points the other words to the cue that states the constraint instead.
    """

    quote = _quote(item.quote.start, item.quote.end, utterance)
    described = (
        f'review_uncovered: the words "{quote["text"]}" at occurrence {quote["occurrence"]} '
        f"state a {item.role.value} constraint that no mention, filter, relation, time, "
        "measure, or unsupported constraint states"
    )
    operands = literal_operands(forms)
    overlapping = [
        (index, mention)
        for index, form in enumerate(forms)
        for mention in form.mentions
        if mention.span.start < item.quote.end and item.quote.start < mention.span.end
    ]
    named = sorted(
        {mention.id for index, mention in overlapping if (index, mention.id) not in operands}
    )
    literal = sorted(
        {mention.id for index, mention in overlapping if (index, mention.id) in operands}
    )
    if named:
        described += (
            f"; mention {', '.join(named)} quotes only part of these words: widen its quote "
            "when they all name one thing, or give the other words their own place when they "
            "state something else"
        )
    if literal:
        described += (
            f"; mention {', '.join(literal)} is a literal value whose quote must stay as it is, "
            "so state the other words in the cue of the filter or relation that cites it"
        )
    return described


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
            for item in goal.filters:
                if item.comparison is not None:
                    semantic.append(item.comparison.comparator_span)
                    semantic.append(item.comparison.value_span)
                    if item.comparison.unit_span is not None:
                        semantic.append(item.comparison.unit_span)
            if goal.relation is not None:
                semantic.append(goal.relation.cue)
                if goal.relation.reach_cue is not None:
                    semantic.append(goal.relation.reach_cue)
            if goal.time.cue is not None:
                semantic.append(goal.time.cue)
            if goal.measure is not None and goal.measure.cue is not None:
                semantic.append(goal.measure.cue)
            if goal.measure is not None and goal.measure.order is not None:
                if goal.measure.order.cue is not None:
                    semantic.append(goal.measure.order.cue)
                if goal.measure.order.limit_span is not None:
                    semantic.append(goal.measure.order.limit_span)
    return semantic, mentions


def _attached(span: SourceSpan, utterance: str) -> SourceSpan | None:
    """Return the rest of the whitespace-delimited word that a mention ends inside."""

    end = span.end
    while end < len(utterance) and not utterance[end].isspace():
        end += 1
    return SourceSpan(start=span.end, end=end) if end > span.end else None


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
    "AnswerKind",
    "ConstraintExtraction",
    "ConstraintRole",
    "ExtractedConstraint",
    "FormReview",
    "answer_kind_unanswered",
    "answer_kinds",
    "describe_merged",
    "describe_uncovered",
    "describe_unexpressible",
    "literal_disagreements",
    "literal_operands",
    "merged_constraints",
    "merged_mentions",
    "extraction_schema",
    "quoted_form",
    "resolve_extraction",
    "review_forms",
    "unacknowledged_constraints",
    "uncovered_constraints",
]
