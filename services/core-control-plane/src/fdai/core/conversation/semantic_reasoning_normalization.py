"""Language-neutral normalization of redundant typed question-form structure."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts.semantic_question_form import (
    FilterRole,
    FormFilter,
    FormGoal,
    GoalLevel,
    MentionDomain,
    SemanticQuestionForm,
    SourceSpan,
)

from .semantic_reasoning_admission import allowed_filter_domains


@dataclass(frozen=True, slots=True)
class FormNormalization:
    """One normalized form and the Core-verified syntactic label spans it moved."""

    form: SemanticQuestionForm
    syntactic_labels: tuple[SourceSpan, ...] = ()


def retained_syntactic_labels(
    form: SemanticQuestionForm,
    *groups: tuple[SourceSpan, ...],
) -> tuple[SourceSpan, ...]:
    """Keep only Core-verified labels whose exact spans remain context in ``form``."""

    context = {(span.start, span.end) for span in form.context}
    retained: dict[tuple[int, int], SourceSpan] = {}
    for spans in groups:
        for span in spans:
            key = (span.start, span.end)
            if key in context:
                retained.setdefault(key, span)
    return tuple(retained.values())


def syntactic_label_covers(
    quote: SourceSpan,
    labels: tuple[SourceSpan, ...],
    utterance: str,
) -> bool:
    """Return whether trusted label spans cover every alphanumeric character in ``quote``."""

    indices = [
        index
        for index in range(quote.start, min(quote.end, len(utterance)))
        if utterance[index].isalnum()
    ]
    return (
        bool(labels)
        and bool(indices)
        and all(any(span.start <= index < span.end for span in labels) for index in indices)
    )


def normalize_redundant_property_filter_labels(
    form: SemanticQuestionForm,
) -> SemanticQuestionForm:
    """Return the normalized form without exposing its internal review receipt."""

    return normalize_redundant_property_filter_labels_with_receipt(form).form


def normalize_redundant_property_filter_labels_with_receipt(
    form: SemanticQuestionForm,
) -> FormNormalization:
    """Move a redundant property-label mention to context without inferring its text.

    A model can represent ``type = compute.vm`` with one PROPERTY mention for the label and one
    allowed RESOURCE_TYPE mention for the operand. The operand can be a companion same-role filter
    or one otherwise-unreferenced mention. The label is syntax, not another constraint. It is
    redundant only when the role has exactly one structural operand and nothing else references
    the label mention.
    """

    if form.alternatives:
        return FormNormalization(form)
    mentions = {mention.id: mention for mention in form.mentions}
    removable: dict[str, list[SourceSpan]] = {}
    syntactic_labels: dict[tuple[int, int], SourceSpan] = {}
    revised_goals: list[FormGoal] = []
    for goal in form.goals:
        allowed_by_role = {
            role: {
                item.mention
                for item in goal.filters
                if mentions[item.mention].domain
                in allowed_filter_domains(role, schema=goal.level is GoalLevel.SCHEMA)
            }
            for role in FilterRole
        }
        property_filters_by_role = {
            role: [
                item
                for item in goal.filters
                if item.role is role and mentions[item.mention].domain is MentionDomain.PROPERTY
            ]
            for role in FilterRole
        }
        detached_by_role: dict[FilterRole, str] = {}
        if len(form.goals) == 1:
            for role in FilterRole:
                if allowed_by_role[role] or len(property_filters_by_role[role]) != 1:
                    continue
                candidates = [
                    mention.id
                    for mention in form.mentions
                    if mention.domain
                    in allowed_filter_domains(role, schema=goal.level is GoalLevel.SCHEMA)
                    and not _mention_referenced_elsewhere(form, mention.id, excluding=None)
                ]
                if len(candidates) == 1:
                    detached_by_role[role] = candidates[0]
        filters = []
        for item in goal.filters:
            mention = mentions[item.mention]
            if mention.domain is MentionDomain.PROPERTY and not _mention_referenced_elsewhere(
                form, mention.id, excluding=item
            ):
                if allowed_by_role[item.role]:
                    removable.setdefault(mention.id, []).extend(
                        span for span in (mention.span, item.cue) if span is not None
                    )
                    syntactic_labels.setdefault(
                        (mention.span.start, mention.span.end), mention.span
                    )
                    continue
                if replacement := detached_by_role.get(item.role):
                    removable.setdefault(mention.id, []).extend(
                        span for span in (mention.span, item.cue) if span is not None
                    )
                    syntactic_labels.setdefault(
                        (mention.span.start, mention.span.end), mention.span
                    )
                    filters.append(item.model_copy(update={"mention": replacement}))
                    continue
            filters.append(item)
        revised_goals.append(goal.model_copy(update={"filters": tuple(filters)}))
    if not removable:
        return FormNormalization(form)
    context_by_span = {(span.start, span.end): span for span in form.context}
    for spans in removable.values():
        for span in spans:
            context_by_span.setdefault((span.start, span.end), span)
    if len(context_by_span) > 32:
        return FormNormalization(form)
    return FormNormalization(
        form.model_copy(
            update={
                "mentions": tuple(item for item in form.mentions if item.id not in removable),
                "goals": tuple(revised_goals),
                "context": tuple(context_by_span.values()),
            }
        ),
        tuple(syntactic_labels.values()),
    )


def _mention_referenced_elsewhere(
    form: SemanticQuestionForm,
    mention_id: str,
    *,
    excluding: FormFilter | None,
) -> bool:
    for mention in form.mentions:
        if mention.qualifier is not None and mention.qualifier.mention == mention_id:
            return True
    for goal in form.goals:
        if mention_id in {goal.subject, goal.counterpart}:
            return True
        if any(item is not excluding and item.mention == mention_id for item in goal.filters):
            return True
        if goal.relation is not None and mention_id in {
            goal.relation.anchor,
            goal.relation.counterpart,
        }:
            return True
        if goal.measure is not None and goal.measure.mention == mention_id:
            return True
    return False


__all__ = [
    "FormNormalization",
    "normalize_redundant_property_filter_labels",
    "normalize_redundant_property_filter_labels_with_receipt",
    "retained_syntactic_labels",
    "syntactic_label_covers",
]
