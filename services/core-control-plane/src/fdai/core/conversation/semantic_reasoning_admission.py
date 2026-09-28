"""Admit or clarify one proposed question form using closed-field checks only.

Admission validates exact spans, level and domain fit, operation requirements,
competing readings, and confidence. It never reads the utterance for meaning; it
only confirms that each span the model cited exists and is not blank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .semantic_reasoning_form import (
    SENSE_ROLES,
    FilterRole,
    FormGoal,
    FormMention,
    GoalLevel,
    GoalOperation,
    MentionDomain,
    MentionForm,
    SemanticQuestionForm,
    SourceSpan,
    SubjectRole,
    SubjectScope,
    TimeKind,
)

DEFAULT_CONFIDENCE_FLOOR = 0.75

_SCHEMA_SUBJECT_DOMAINS = frozenset(
    {
        MentionDomain.OBJECT_TYPE,
        MentionDomain.DECLARATION_KIND,
        MentionDomain.RESOURCE_CLASS,
        MentionDomain.RESOURCE_TYPE,
    }
)
_COLLECTION_SUBJECT_DOMAINS = frozenset(
    {MentionDomain.OBJECT_TYPE, MentionDomain.RESOURCE_TYPE, MentionDomain.RESOURCE_CLASS}
)
_FILTER_DOMAINS: dict[FilterRole, frozenset[MentionDomain]] = {
    FilterRole.TYPE: _COLLECTION_SUBJECT_DOMAINS,
    FilterRole.STATE: frozenset({MentionDomain.STATE}),
    FilterRole.HEALTH: frozenset({MentionDomain.HEALTH}),
    FilterRole.REGION: frozenset({MentionDomain.REGION}),
    FilterRole.NAME_FRAGMENT: frozenset({MentionDomain.INSTANCE}),
    FilterRole.SCOPE: frozenset({MentionDomain.INSTANCE}),
}
_SCHEMA_FILTER_DOMAINS: dict[FilterRole, frozenset[MentionDomain]] = {
    FilterRole.TYPE: frozenset({MentionDomain.DECLARATION_KIND}),
}
_ANCHOR_FORMS = frozenset({MentionForm.IDENTIFIER, MentionForm.NAME})
_REFERENCE_FORMS = frozenset({MentionForm.ANAPHOR, MentionForm.ORDINAL})
# Traverse needs a stated relation; impact and path carry a reviewed implied relation.
_RELATION_OPERATIONS = frozenset({GoalOperation.TRAVERSE})
_MEASURE_OPERATIONS = frozenset({GoalOperation.LOOKUP, GoalOperation.AGGREGATE, GoalOperation.RANK})


class AdmissionDisposition(StrEnum):
    ADMITTED = "admitted"
    CLARIFY = "clarify"
    REVIEW = "review"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class FormAdmission:
    """Typed admission outcome; only ``ADMITTED`` forms may compile."""

    disposition: AdmissionDisposition
    reasons: tuple[str, ...]
    form: SemanticQuestionForm
    mention_text: dict[str, str] = field(default_factory=dict)
    needs_continuation: bool = False


def admit_question_form(
    form: SemanticQuestionForm,
    *,
    utterance: str,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> FormAdmission:
    """Return the admission disposition and the exact text of every mention."""

    if not 0.0 < confidence_floor <= 1.0:
        raise ValueError("confidence floor MUST be in (0, 1]")
    invalid: list[str] = []
    mention_text: dict[str, str] = {}
    for mention in form.mentions:
        text = _span_text(mention.span, utterance)
        if text is None:
            invalid.append(f"mention_span_invalid:{mention.id}")
            continue
        mention_text[mention.id] = text
    for goal in form.goals:
        invalid.extend(_goal_span_failures(goal, utterance))
        invalid.extend(_goal_shape_failures(goal, form))
    if invalid:
        return FormAdmission(AdmissionDisposition.INVALID, tuple(invalid), form, mention_text)
    if form.alternatives:
        reasons = tuple(f"competing_reading:{item.goal}" for item in form.alternatives)
        return FormAdmission(AdmissionDisposition.CLARIFY, reasons, form, mention_text)
    contradictions = _relation_contradictions(form)
    if contradictions:
        return FormAdmission(AdmissionDisposition.CLARIFY, contradictions, form, mention_text)
    unused = _unused_mentions(form)
    if unused:
        return FormAdmission(AdmissionDisposition.CLARIFY, unused, form, mention_text)
    low = tuple(
        f"low_confidence:{goal.id}" for goal in form.goals if goal.confidence < confidence_floor
    )
    if low:
        return FormAdmission(AdmissionDisposition.REVIEW, low, form, mention_text)
    return FormAdmission(
        AdmissionDisposition.ADMITTED,
        (),
        form,
        mention_text,
        needs_continuation=form.remaining_goals,
    )


def _span_text(span: SourceSpan, utterance: str) -> str | None:
    if span.end > len(utterance):
        return None
    text = utterance[span.start : span.end]
    if not text.strip() or text != text.strip():
        return None
    return text


def _goal_span_failures(goal: FormGoal, utterance: str) -> list[str]:
    spans = [("goal_cue", goal.cue)]
    if goal.relation is not None:
        spans.append(("relation_cue", goal.relation.cue))
    if goal.time.cue is not None:
        spans.append(("time_cue", goal.time.cue))
    return [
        f"{name}_span_invalid:{goal.id}"
        for name, span in spans
        if _span_text(span, utterance) is None
    ]


def _goal_shape_failures(goal: FormGoal, form: SemanticQuestionForm) -> list[str]:
    failures: list[str] = []
    subject = form.mention(goal.subject) if goal.subject is not None else None
    # A subject restated by one of the goal's own filters is subsumed by that filter.
    restated = subject is not None and any(item.mention == subject.id for item in goal.filters)
    related = goal.relation is not None and goal.relation.anchor is not None
    if goal.level is GoalLevel.SCHEMA:
        if subject is not None and subject.domain not in _SCHEMA_SUBJECT_DOMAINS:
            failures.append(f"schema_subject_domain:{goal.id}")
        if goal.subject_scope is SubjectScope.ANCHOR and subject is None:
            failures.append(f"schema_subject_missing:{goal.id}")
    elif restated or related:
        pass
    elif goal.subject_scope is SubjectScope.ANCHOR:
        if subject is None:
            failures.append(f"anchor_missing:{goal.id}")
        elif subject.domain is not MentionDomain.INSTANCE or subject.form not in _ANCHOR_FORMS:
            failures.append(f"anchor_domain:{goal.id}")
    elif (
        goal.subject_scope is SubjectScope.COLLECTION
        and subject is not None
        and subject.domain not in _COLLECTION_SUBJECT_DOMAINS
    ):
        failures.append(f"collection_subject_domain:{goal.id}")
    filter_domains = _SCHEMA_FILTER_DOMAINS if goal.level is GoalLevel.SCHEMA else _FILTER_DOMAINS
    for item in goal.filters:
        allowed = filter_domains.get(item.role, frozenset())
        if form.mention(item.mention).domain not in allowed:
            failures.append(f"filter_domain:{goal.id}:{item.role.value}")
    if goal.operation in _RELATION_OPERATIONS and goal.relation is None:
        failures.append(f"relation_required:{goal.id}")
    if goal.relation is not None:
        failures.extend(_relation_failures(goal, form, subject))
    if goal.operation in _MEASURE_OPERATIONS and goal.measure is None:
        failures.append(f"measure_required:{goal.id}")
    if goal.operation is GoalOperation.HISTORY and goal.time.kind is TimeKind.FUTURE:
        failures.append(f"history_future_time:{goal.id}")
    if goal.operation is GoalOperation.DESCRIBE_SCHEMA and goal.level is not GoalLevel.SCHEMA:
        failures.append(f"describe_schema_level:{goal.id}")
    if goal.subject_scope is SubjectScope.GOAL_OUTPUT and not goal.depends_on:
        failures.append(f"goal_output_dependency_missing:{goal.id}")
    if (
        goal.subject_scope is SubjectScope.PRIOR_RESULT
        and subject is not None
        and subject.form not in _REFERENCE_FORMS
    ):
        failures.append(f"prior_result_reference_form:{goal.id}")
    return failures


def _relation_failures(
    goal: FormGoal,
    form: SemanticQuestionForm,
    subject: FormMention | None,
) -> list[str]:
    relation = goal.relation
    if relation is None:
        return []
    failures: list[str] = []
    if relation.anchor_position is None or (
        relation.result_role is not SubjectRole.EITHER
        and relation.result_role not in SENSE_ROLES[relation.sense]
    ):
        failures.append(f"relation_role_mismatch:{goal.id}")
    if goal.level is GoalLevel.SCHEMA:
        return failures
    anchor = form.mention(relation.anchor) if relation.anchor is not None else subject
    referenced = goal.subject_scope is SubjectScope.PRIOR_RESULT and any(
        mention.form in _REFERENCE_FORMS for mention in form.mentions
    )
    if not referenced and (
        anchor is None
        or anchor.domain is not MentionDomain.INSTANCE
        or anchor.form not in _ANCHOR_FORMS | _REFERENCE_FORMS
    ):
        failures.append(f"relation_anchor_missing:{goal.id}")
    return failures


def _unused_mentions(form: SemanticQuestionForm) -> tuple[str, ...]:
    """Return declared mentions that no goal accounts for; each is a dropped restriction.

    A mention inside a used cue restates that cue, and the one reference mention of
    a prior-result goal without a subject is that goal's subject.
    """

    cited = set(form.cited_mentions())
    cues = [
        span
        for goal in form.goals
        for span in (
            goal.cue,
            goal.relation.cue if goal.relation is not None else None,
            goal.time.cue,
        )
        if span is not None
    ]
    references = [mention.id for mention in form.mentions if mention.form in _REFERENCE_FORMS]
    if len(references) == 1 and any(
        goal.subject_scope is SubjectScope.PRIOR_RESULT and goal.subject is None
        for goal in form.goals
    ):
        cited.add(references[0])
    return tuple(
        f"mention_unused:{mention.id}"
        for mention in form.mentions
        if mention.id not in cited
        and not any(mention.span.start < cue.end and cue.start < mention.span.end for cue in cues)
    )


def _relation_contradictions(form: SemanticQuestionForm) -> tuple[str, ...]:
    return tuple(
        f"relation_roles_inconsistent:{goal.id}"
        for goal in form.goals
        if goal.relation is not None and not goal.relation.roles_consistent
    )


__all__ = [
    "DEFAULT_CONFIDENCE_FLOOR",
    "AdmissionDisposition",
    "FormAdmission",
    "admit_question_form",
]
