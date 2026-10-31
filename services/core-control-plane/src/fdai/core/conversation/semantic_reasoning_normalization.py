"""Language-neutral normalization of redundant typed question-form structure."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts.semantic_question_form import (
    FilterRole,
    FormFilter,
    FormGoal,
    GoalLevel,
    GoalOperation,
    MentionDomain,
    SemanticQuestionForm,
    SourceSpan,
    SubjectScope,
)

from .semantic_reasoning_admission import allowed_filter_domains


@dataclass(frozen=True, slots=True)
class FormNormalization:
    """One normalized form and the Core-verified syntactic label spans it moved."""

    form: SemanticQuestionForm
    syntactic_labels: tuple[SourceSpan, ...] = ()


def merge_syntactic_labels(*groups: tuple[SourceSpan, ...]) -> tuple[SourceSpan, ...]:
    """Deduplicate Core-verified labels retained by an accepted meaning-preserving repair."""

    retained: dict[tuple[int, int], SourceSpan] = {}
    for spans in groups:
        for span in spans:
            key = (span.start, span.end)
            retained.setdefault(key, span)
    return tuple(retained.values())


def syntactic_label_covers(
    quote: SourceSpan,
    labels: tuple[SourceSpan, ...],
    utterance: str,
) -> bool:
    """Return whether trusted label spans cover every alphanumeric character in ``quote``."""

    start = max(0, quote.start)
    end = min(max(start, quote.end), len(utterance))
    indices = [index for index in range(start, end) if utterance[index].isalnum()]
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
    form = _canonicalize_inverted_type_roles(form)
    mentions = {mention.id: mention for mention in form.mentions}
    removable: dict[str, list[SourceSpan]] = {}
    cue_labels = _typed_filter_cue_labels(form)
    syntactic_labels = dict(cue_labels)
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
        return FormNormalization(form, tuple(cue_labels.values()))
    context_by_span = {(span.start, span.end): span for span in form.context}
    for spans in removable.values():
        for span in spans:
            context_by_span.setdefault((span.start, span.end), span)
    if len(context_by_span) > 32:
        return FormNormalization(form, tuple(cue_labels.values()))
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


def _typed_filter_cue_labels(
    form: SemanticQuestionForm,
) -> dict[tuple[int, int], SourceSpan]:
    """Return non-mention cue spans attached to domain-valid typed filters."""

    typed_mentions = {mention.id: mention for mention in form.mentions}
    labels: dict[tuple[int, int], SourceSpan] = {}
    for goal in form.goals:
        for item in goal.filters:
            cue = item.cue
            mention = typed_mentions[item.mention]
            if (
                cue is None
                or mention.domain
                not in allowed_filter_domains(item.role, schema=goal.level is GoalLevel.SCHEMA)
                or any(_overlaps(cue, candidate.span) for candidate in form.mentions)
            ):
                continue
            labels.setdefault((cue.start, cue.end), cue)
    return labels


def _overlaps(left: SourceSpan, right: SourceSpan) -> bool:
    return left.start < right.end and right.start < left.end


def _canonicalize_inverted_type_roles(form: SemanticQuestionForm) -> SemanticQuestionForm:
    """Put the broader ObjectType subject before one narrower ResourceType filter."""

    if len(form.goals) != 1:
        return form
    goal = form.goals[0]
    if (
        goal.level is not GoalLevel.INSTANCE
        or goal.operation is not GoalOperation.SELECT
        or goal.subject_scope is not SubjectScope.COLLECTION
        or goal.subject is None
    ):
        return form
    mentions = {mention.id: mention for mention in form.mentions}
    subject = mentions[goal.subject]
    type_filters = [item for item in goal.filters if item.role is FilterRole.TYPE]
    if (
        subject.domain is not MentionDomain.RESOURCE_TYPE
        or len(type_filters) != 1
        or mentions[type_filters[0].mention].domain is not MentionDomain.OBJECT_TYPE
        or not _type_roles_are_isolated(form, goal.subject, type_filters[0])
    ):
        return form
    type_filter = type_filters[0]
    filters = tuple(
        item.model_copy(update={"mention": goal.subject}) if item is type_filter else item
        for item in goal.filters
    )
    return form.model_copy(
        update={
            "goals": (
                goal.model_copy(
                    update={
                        "subject": type_filter.mention,
                        "filters": filters,
                    }
                ),
            )
        }
    )


def _type_roles_are_isolated(
    form: SemanticQuestionForm,
    subject_id: str,
    type_filter: FormFilter,
) -> bool:
    """Return whether swapping the two type roles changes no other reference."""

    type_id = type_filter.mention
    if any(
        mention.qualifier is not None and mention.qualifier.mention in {subject_id, type_id}
        for mention in form.mentions
    ):
        return False
    goal = form.goals[0]
    if goal.counterpart in {subject_id, type_id}:
        return False
    if any(
        item is not type_filter and item.mention in {subject_id, type_id} for item in goal.filters
    ):
        return False
    if goal.relation is not None and {
        goal.relation.anchor,
        goal.relation.counterpart,
    } & {subject_id, type_id}:
        return False
    return goal.measure is None or goal.measure.mention not in {subject_id, type_id}


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
    "merge_syntactic_labels",
    "normalize_redundant_property_filter_labels",
    "normalize_redundant_property_filter_labels_with_receipt",
    "syntactic_label_covers",
]
