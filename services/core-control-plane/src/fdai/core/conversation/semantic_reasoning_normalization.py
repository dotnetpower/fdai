"""Language-neutral normalization of redundant typed question-form structure."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from fdai_service_contracts.semantic_question_form import (
    FilterRole,
    FormFilter,
    FormGoal,
    GoalLevel,
    GoalOperation,
    MentionDomain,
    MentionForm,
    SemanticQuestionForm,
    SourceSpan,
    SubjectScope,
)

from .semantic_reasoning_admission import (
    AdmissionDisposition,
    FormAdmission,
    SpanAccounting,
    admit_question_form,
    allowed_filter_domains,
)
from .semantic_reasoning_concepts import ConceptOutcome, ConceptSelectionReceipt


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
    form = _canonicalize_prior_result_roles(_canonicalize_inverted_type_roles(form))
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
            if (
                item.role is FilterRole.TYPE
                and goal.subject is not None
                and item.mention == goal.subject
                and len(goal.filters) > 1
            ):
                if item.cue is not None:
                    removable.setdefault(f"_self_cue_{goal.id}", []).append(item.cue)
                    syntactic_labels.setdefault((item.cue.start, item.cue.end), item.cue)
                continue
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


def _canonicalize_prior_result_roles(form: SemanticQuestionForm) -> SemanticQuestionForm:
    """Align subject_scope and mention form when either side explicitly declares prior_result."""

    mentions = {mention.id: mention for mention in form.mentions}
    has_reference_mention = any(
        item.form in {MentionForm.ANAPHOR, MentionForm.ORDINAL} for item in form.mentions
    )
    updated_mentions = dict(mentions)
    updated_goals: list[FormGoal] = []
    changed = False
    for goal in form.goals:
        subject_id = goal.subject
        if subject_id is not None and subject_id in mentions:
            subj = updated_mentions[subject_id]
            if subj.form in {MentionForm.ANAPHOR, MentionForm.ORDINAL}:
                if subj.domain is not MentionDomain.INSTANCE:
                    updated_mentions[subject_id] = subj.model_copy(
                        update={"domain": MentionDomain.INSTANCE}
                    )
                    changed = True
                if goal.subject_scope is SubjectScope.COLLECTION:
                    goal = goal.model_copy(update={"subject_scope": SubjectScope.PRIOR_RESULT})
                    changed = True
            elif (
                goal.subject_scope is SubjectScope.PRIOR_RESULT and subj.form is MentionForm.CONCEPT
            ):
                if subj.domain is MentionDomain.OBJECT_TYPE and not goal.filters:
                    updated_mentions[subject_id] = subj.model_copy(
                        update={"form": MentionForm.ANAPHOR, "domain": MentionDomain.INSTANCE}
                    )
                    changed = True
                elif not has_reference_mention and (
                    subj.domain in {MentionDomain.RESOURCE_TYPE, MentionDomain.RESOURCE_CLASS}
                    or bool(goal.filters)
                ):
                    goal = goal.model_copy(update={"subject_scope": SubjectScope.COLLECTION})
                    changed = True
        updated_goals.append(goal)
    if not changed:
        return form
    return form.model_copy(
        update={
            "mentions": tuple(updated_mentions[item.id] for item in form.mentions),
            "goals": tuple(updated_goals),
        }
    )


def promote_contextual_admission(
    form: SemanticQuestionForm,
    admission: FormAdmission,
    *,
    utterance: str,
    has_context: bool,
    has_prior_handles: bool,
    accounting: SpanAccounting,
) -> tuple[SemanticQuestionForm, FormAdmission]:
    """Promote bare prior-result follow-ups and relax single-reading confidence under context."""

    if (
        has_context
        and len(form.goals) == 1
        and form.alternatives
        and all(atom.field == "subject_scope" for item in form.alternatives for atom in item.atoms)
        and not any(
            item.form in {MentionForm.ANAPHOR, MentionForm.ORDINAL} for item in form.mentions
        )
        and (
            bool(form.goals[0].filters)
            or (
                form.goals[0].subject is not None
                and form.mention(form.goals[0].subject).domain
                in {MentionDomain.RESOURCE_TYPE, MentionDomain.RESOURCE_CLASS}
            )
        )
    ):
        form = form.model_copy(
            update={
                "goals": (
                    form.goals[0].model_copy(update={"subject_scope": SubjectScope.COLLECTION}),
                ),
                "alternatives": (),
            }
        )
        admission = admit_question_form(
            form,
            utterance=utterance,
            confidence_floor=0.35,
            accounting=accounting,
        )
    if (
        has_prior_handles
        and len(form.goals) == 1
        and form.goals[0].level is GoalLevel.INSTANCE
        and form.goals[0].effective_operation in {GoalOperation.SELECT, GoalOperation.COUNT}
        and form.goals[0].subject_scope is SubjectScope.COLLECTION
        and not form.goals[0].filters
        and form.goals[0].relation is None
        and form.goals[0].measure is None
        and (
            form.goals[0].subject is None
            or (
                form.goals[0].effective_operation is GoalOperation.SELECT
                and form.mention(form.goals[0].subject).domain is MentionDomain.OBJECT_TYPE
            )
        )
    ):
        subj_id = form.goals[0].subject
        form = form.model_copy(
            update={
                "mentions": tuple(
                    item.model_copy(
                        update={"form": MentionForm.ANAPHOR, "domain": MentionDomain.INSTANCE}
                    )
                    if item.id == subj_id
                    else item
                    for item in form.mentions
                ),
                "goals": (
                    form.goals[0].model_copy(update={"subject_scope": SubjectScope.PRIOR_RESULT}),
                ),
            }
        )
        admission = admit_question_form(
            form,
            utterance=utterance,
            confidence_floor=0.35 if has_context else 0.75,
            accounting=accounting,
        )
    if (
        admission.disposition is AdmissionDisposition.REVIEW
        and has_context
        and not form.alternatives
    ):
        admission = admit_question_form(
            form,
            utterance=utterance,
            confidence_floor=0.35,
            accounting=accounting,
        )
    return form, admission


def retype_unfound_subject_to_prior_result(
    admission: FormAdmission,
    receipt: ConceptSelectionReceipt,
    *,
    utterance: str,
    has_context: bool,
    has_prior_handles: bool,
) -> FormAdmission:
    """Convert an unfound generic collection subject to a prior-result anaphor."""

    if not has_prior_handles or len(admission.form.goals) != 1:
        return admission
    g0 = admission.form.goals[0]
    subj_binding = receipt.binding(g0.subject) if g0.subject is not None else None
    if not (
        g0.level is GoalLevel.INSTANCE
        and g0.effective_operation in {GoalOperation.SELECT, GoalOperation.COUNT}
        and g0.subject_scope is SubjectScope.COLLECTION
        and g0.subject is not None
        and not g0.filters
        and g0.relation is None
        and subj_binding is not None
        and (
            subj_binding.outcome in {ConceptOutcome.NOT_FOUND, ConceptOutcome.AMBIGUOUS}
            or not subj_binding.values
        )
    ):
        return admission
    retyped_form = admission.form.model_copy(
        update={
            "mentions": tuple(
                item.model_copy(
                    update={"form": MentionForm.ANAPHOR, "domain": MentionDomain.INSTANCE}
                )
                if item.id == g0.subject
                else item
                for item in admission.form.mentions
            ),
            "goals": (g0.model_copy(update={"subject_scope": SubjectScope.PRIOR_RESULT}),),
        }
    )
    retyped_admission = admit_question_form(
        retyped_form,
        utterance=utterance,
        confidence_floor=0.35 if has_context else 0.75,
        accounting=SpanAccounting(required=False),
    )
    return (
        retyped_admission
        if retyped_admission.disposition is AdmissionDisposition.ADMITTED
        else admission
    )


_INVERTED_TYPE_ROLE_OPERATIONS = frozenset(
    {
        GoalOperation.SELECT,
        GoalOperation.COUNT,
        GoalOperation.AGGREGATE,
        GoalOperation.HISTORY,
        GoalOperation.RANK,
    }
)


def _canonicalize_inverted_type_roles(form: SemanticQuestionForm) -> SemanticQuestionForm:
    """Put the broader ObjectType subject before one narrower ResourceType filter."""

    if len(form.goals) != 1:
        return form
    goal = form.goals[0]
    if (
        goal.level is not GoalLevel.INSTANCE
        or goal.operation not in _INVERTED_TYPE_ROLE_OPERATIONS
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


def attach_hangul_unaccounted_context(
    resolution: Any,
    admission: FormAdmission | None,
    *,
    utterance: str,
    accounting: SpanAccounting,
) -> tuple[Any, FormAdmission | None]:
    """Attach unaccounted Hangul particles to context; blind review checks constraints."""

    form = resolution.form
    if (
        form is None
        or form.remaining_goals
        or admission is None
        or admission.disposition is not AdmissionDisposition.INVALID
        or not admission.reasons
        or not all(reason.startswith("span_unaccounted:") for reason in admission.reasons)
    ):
        return resolution, admission
    spans = {(span.start, span.end): span for span in form.context}
    for reason in admission.reasons:
        _, _, where = reason.partition(":")
        start_str, _, end_str = where.partition("-")
        if not (start_str.isdigit() and end_str.isdigit()):
            return resolution, admission
        start, end = int(start_str), int(end_str)
        fragment = utterance[start:end] if 0 <= start < end <= len(utterance) else ""
        if not fragment or not all("가" <= ch <= "힣" or ch.isspace() for ch in fragment):
            return resolution, admission
        spans.setdefault((start, end), SourceSpan(start=start, end=end))
    if len(spans) > 32:
        return resolution, admission
    updated_form = form.model_copy(update={"context": tuple(spans.values())})
    updated_admission = admit_question_form(
        updated_form, utterance=utterance, accounting=accounting
    )
    if updated_admission.disposition is AdmissionDisposition.INVALID:
        return resolution, admission
    return replace(resolution, form=updated_form), updated_admission


__all__ = [
    "FormNormalization",
    "attach_hangul_unaccounted_context",
    "merge_syntactic_labels",
    "normalize_redundant_property_filter_labels",
    "normalize_redundant_property_filter_labels_with_receipt",
    "syntactic_label_covers",
]
