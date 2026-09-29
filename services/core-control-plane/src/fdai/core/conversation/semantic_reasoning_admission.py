"""Admit or clarify one proposed question form using closed-field checks only.

Admission validates exact spans, level and domain fit, operation requirements,
competing readings, and confidence. It never reads the utterance for meaning; it
only confirms that each span the model cited exists and is not blank, that
decimal digits inside a time cue equal the typed time value the model proposed,
and that every letter, digit, math symbol, and currency symbol lies inside some span
the model quoted, so no stated word is dropped without the model's explicit judgment.
"""

from __future__ import annotations

import string
import unicodedata
from collections.abc import Sequence
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
    RelationReach,
    RelationScope,
    RelationSense,
    SemanticQuestionForm,
    SourceSpan,
    SubjectPosition,
    SubjectRole,
    SubjectScope,
    TimeKind,
    Want,
)

DEFAULT_CONFIDENCE_FLOOR = 0.75
MAX_UNACCOUNTED_REASONS = 8

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
    # A declaration kind scoped to an ObjectType, as in the LinkTypes in Workload.
    FilterRole.SCOPE: frozenset({MentionDomain.OBJECT_TYPE}),
}
_ANCHOR_FORMS = frozenset({MentionForm.IDENTIFIER, MentionForm.NAME})
_IDENTIFIER_ALNUM = frozenset(string.ascii_letters + string.digits)
_IDENTIFIER_JOINERS = frozenset("._/-")
_REFERENCE_FORMS = frozenset({MentionForm.ANAPHOR, MentionForm.ORDINAL})
# Traverse needs a stated relation; impact and path carry a reviewed implied relation.
_RELATION_OPERATIONS = frozenset({GoalOperation.TRAVERSE})
_MEASURE_OPERATIONS = frozenset({GoalOperation.LOOKUP, GoalOperation.AGGREGATE, GoalOperation.RANK})


@dataclass(frozen=True, slots=True)
class SpanAccounting:
    """Whether admission accounts for every word, and the spans earlier passes quoted.

    A form that sets ``remaining_goals`` leaves later goals' words to later passes,
    so only a final pass is checked, against its own spans and the spans earlier passes
    gave meaning to. Earlier context never carries over, because an earlier pass must
    not declare a later goal's words to state no constraint.
    """

    required: bool = True
    accounted: frozenset[tuple[int, int]] = frozenset()

    def after(self, form: SemanticQuestionForm) -> SpanAccounting:
        """Return the accounting for the next pass after ``form`` was admitted."""

        spans = {(span.start, span.end) for span in form.declared_spans(context=False)}
        return SpanAccounting(self.required, self.accounted | spans)


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
    # Goals whose typed time value came from words without digits, so it is the model's reading.
    judged_times: frozenset[str] = frozenset()


def admit_question_form(
    form: SemanticQuestionForm,
    *,
    utterance: str,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
    accounting: SpanAccounting = SpanAccounting(),  # noqa: B008 - immutable value object
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
        if mention.domain is MentionDomain.INSTANCE and _splits_identifier(mention.span, utterance):
            invalid.append(f"mention_span_partial:{mention.id}")
            continue
        invalid.extend(_position_failures(mention, text))
        mention_text[mention.id] = text
    invalid.extend(_overlapping_mentions(form))
    invalid.extend(_qualifier_failures(form))
    judged: set[str] = set()
    fractional: list[str] = []
    for goal in form.goals:
        invalid.extend(_goal_span_failures(goal, utterance))
        invalid.extend(_goal_shape_failures(goal, form))
        check = _time_value_check(goal, utterance)
        if check is _TimeCheck.MISMATCH:
            invalid.append(f"time_value_mismatch:{goal.id}")
        elif check in {_TimeCheck.FRACTIONAL, _TimeCheck.COMPOUND}:
            fractional.append(f"time_value_{check.value}:{goal.id}")
        elif check is _TimeCheck.JUDGED:
            judged.add(goal.id)
    if accounting.required and not form.remaining_goals:
        invalid.extend(_unaccounted_runs(form, utterance, accounting.accounted))
    if invalid:
        return FormAdmission(AdmissionDisposition.INVALID, tuple(invalid), form, mention_text)
    if form.alternatives:
        reasons = tuple(f"competing_reading:{item.goal}" for item in form.alternatives)
        return FormAdmission(AdmissionDisposition.CLARIFY, reasons, form, mention_text)
    if form.unsupported_constraints:
        # A stated constraint no closed field expresses is never dropped from the answer.
        reasons = tuple(
            f"constraint_unsupported:{span.start}-{span.end}"
            for span in form.unsupported_constraints
        )
        return FormAdmission(AdmissionDisposition.CLARIFY, reasons, form, mention_text)
    # A fractional or compound amount cannot be checked, so the operator restates it.
    contradictions = (*_relation_contradictions(form), *fractional)
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
        judged_times=frozenset(judged),
    )


def _position_failures(mention: FormMention, text: str) -> list[str]:
    """Return why an ordinal's typed position is missing, stray, or unlike its digits.

    Only an ordinal names a position. When its words carry decimal digits, such as 3rd or
    3번째, they must equal the position; a position read from words, such as first or
    첫 번째, stays the model's reading.
    """

    if mention.form is not MentionForm.ORDINAL:
        return [f"position_unexpected:{mention.id}"] if mention.position is not None else []
    if mention.position is None or mention.position == 0:
        return [f"ordinal_position_missing:{mention.id}"]
    digits = [value for value in _decimal_numbers(text) if value is not None]
    if digits and digits != [abs(mention.position)]:
        return [f"ordinal_position_mismatch:{mention.id}"]
    return []


def _unaccounted_runs(
    form: SemanticQuestionForm, utterance: str, accounted: frozenset[tuple[int, int]]
) -> list[str]:
    """Return a content-free reason for each run of accountable characters no span holds.

    Core classifies characters only by Unicode category, to check that the model placed
    every letter, digit, and math or currency symbol inside a mention, a cue, context, or
    an unsupported constraint; it never interprets what the characters mean. A particle
    attached to an instance name or identifier in the same whitespace-delimited word is
    accounted with it, because that quote is an exact lookup key a repair must never
    widen; the blind review still judges any restriction such a particle states. Any
    other character, such as a comparison sign, needs its own place.
    """

    covered = bytearray(len(utterance))
    suffixes = [
        (mention.span.end, _word_end(utterance, mention.span.end))
        for mention in form.mentions
        if mention.domain is MentionDomain.INSTANCE and mention.form in _ANCHOR_FORMS
    ]
    for start, end in (
        *((span.start, span.end) for span in form.declared_spans()),
        *accounted,
        *suffixes,
    ):
        low, high = max(start, 0), min(end, len(utterance))
        if low < high:
            covered[low:high] = b"\x01" * (high - low)
    missing: list[str] = []
    run_start: int | None = None
    for index, character in enumerate(utterance):
        pending = not covered[index] and _accountable(character)
        if pending and run_start is None:
            run_start = index
        elif not pending and run_start is not None:
            missing.append(f"span_unaccounted:{run_start}-{index}")
            run_start = None
    if run_start is not None:
        missing.append(f"span_unaccounted:{run_start}-{len(utterance)}")
    return missing[:MAX_UNACCOUNTED_REASONS]


def _word_end(utterance: str, index: int) -> int:
    """Return where the whitespace-delimited word that ``index`` falls inside ends."""

    while index < len(utterance) and not utterance[index].isspace():
        index += 1
    return index


def _accountable(character: str) -> bool:
    return character.isalnum() or unicodedata.category(character) in {"Sm", "Sc"}


class _TimeCheck(StrEnum):
    STATED = "stated"
    JUDGED = "judged"
    MISMATCH = "mismatch"
    FRACTIONAL = "fractional"
    COMPOUND = "compound"


def _time_value_check(goal: FormGoal, utterance: str) -> _TimeCheck | None:
    """Compare decimal digits in a goal's time cue with its typed value.

    Digits are compared as whole numbers only. Words such as ``three`` or
    ``yesterday`` carry no digits, so their typed reading stays the model's and is
    marked as judged. A fractional amount such as ``1.5``, or several amounts such as
    ``1 hour 30 minutes``, cannot be checked against one typed value.
    """

    time = goal.time
    if time.value is None:
        return None
    if time.cue is None or time.cue.end > len(utterance):
        return _TimeCheck.JUDGED
    numbers = _decimal_numbers(utterance[time.cue.start : time.cue.end])
    if not numbers:
        return _TimeCheck.JUDGED
    if None in numbers:
        return _TimeCheck.FRACTIONAL
    if len(numbers) > 1:
        return _TimeCheck.COMPOUND
    if time.value.duration is not None:
        expected = time.value.duration.amount
    else:
        expected = abs(time.value.calendar_offset_days or 0)
    return _TimeCheck.STATED if set(numbers) == {expected} else _TimeCheck.MISMATCH


def _decimal_numbers(text: str) -> tuple[int | None, ...]:
    """Return each decimal number in ``text``; a fractional number is ``None``.

    Digits joined by ``,`` in groups of three form one grouped number, as in 1,440;
    digits joined by ``.`` form one fractional number, as in 1.5.
    """

    numbers: list[int | None] = []
    index = 0
    while index < len(text):
        if not text[index].isdecimal():
            index += 1
            continue
        groups = [""]
        joiners: list[str] = []
        while index < len(text):
            character = text[index]
            if character.isdecimal():
                groups[-1] += str(unicodedata.decimal(character))
            elif character in ",." and index + 1 < len(text) and text[index + 1].isdecimal():
                joiners.append(character)
                groups.append("")
            else:
                break
            index += 1
        if "." in joiners:
            numbers.append(None)
        elif joiners and all(len(group) == 3 for group in groups[1:]):
            numbers.append(int("".join(groups)))
        else:
            numbers.extend(int(group) for group in groups)
    return tuple(numbers)


def _span_text(span: SourceSpan, utterance: str) -> str | None:
    if span.end > len(utterance):
        return None
    text = utterance[span.start : span.end]
    if not text.strip() or text != text.strip():
        return None
    return text


def _splits_identifier(span: SourceSpan, utterance: str) -> bool:
    """Return whether an instance quote cuts through a longer identifier token.

    This checks only the characters adjacent to the model's quote, so a quote of
    ``rg-app`` inside ``rg-app-dev`` cannot bind a different resource, while a
    sentence period after ``rg-app`` still admits it.
    """

    return _continues(utterance, span.start - 1, -1) or _continues(utterance, span.end, 1)


def _continues(utterance: str, index: int, step: int) -> bool:
    """Return whether an identifier continues at ``index`` when read in ``step`` direction.

    An ASCII letter or digit always continues it; a joiner continues it only when an
    ASCII letter or digit lies beyond the joiner in the same direction.
    """

    if not 0 <= index < len(utterance):
        return False
    character = utterance[index]
    if character in _IDENTIFIER_ALNUM:
        return True
    beyond = index + step
    return (
        character in _IDENTIFIER_JOINERS
        and 0 <= beyond < len(utterance)
        and utterance[beyond] in _IDENTIFIER_ALNUM
    )


def _goal_span_failures(goal: FormGoal, utterance: str) -> list[str]:
    spans = [("goal_cue", goal.cue)]
    if goal.relation is not None:
        spans.append(("relation_cue", goal.relation.cue))
        if goal.relation.reach_cue is not None:
            spans.append(("reach_cue", goal.relation.reach_cue))
    if goal.time.cue is not None:
        spans.append(("time_cue", goal.time.cue))
    return [
        f"{name}_span_invalid:{goal.id}"
        for name, span in spans
        if _span_text(span, utterance) is None
    ]


def allowed_filter_domains(role: FilterRole, *, schema: bool) -> tuple[MentionDomain, ...]:
    """Return the mention domains a filter role accepts at instance or schema level."""

    table = _SCHEMA_FILTER_DOMAINS if schema else _FILTER_DOMAINS
    return tuple(sorted(table.get(role, frozenset()), key=lambda item: item.value))


def _qualifier_failures(form: SemanticQuestionForm) -> list[str]:
    """Return a reason for each qualifier that does not place one named resource in another.

    A kind, state, or relation of the results is a filter or a relation; stated as a
    qualifier it would reach no builder, so the one repair names the misplaced atom. A
    qualifier on a goal subject that names one of that goal's own filters only restates
    the filter, so it is read with it.
    """

    domains = {mention.id: mention.domain for mention in form.mentions}
    return [
        f"qualifier_not_instance:{mention.id}"
        for mention in form.mentions
        if mention.qualifier is not None
        and not restates_filter(form.goals, mention.id, mention.qualifier.mention)
        and (
            mention.domain is not MentionDomain.INSTANCE
            or domains.get(mention.qualifier.mention) is not MentionDomain.INSTANCE
        )
    ]


def restates_filter(goals: Sequence[FormGoal], mention_id: str, qualifier_id: str) -> bool:
    """Return whether a qualifier on a goal subject names one of that goal's filters."""

    return any(
        goal.subject == mention_id and any(item.mention == qualifier_id for item in goal.filters)
        for goal in goals
    )


def _overlapping_mentions(form: SemanticQuestionForm) -> list[str]:
    """Return a reason for each mention whose span overlaps an earlier mention's span.

    One mention grounds one thing, so words two mentions share, such as a concept
    mention quoting a whole phrase around a name, would be grounded twice.
    """

    seen: list[tuple[int, int]] = []
    reasons: list[str] = []
    for mention in form.mentions:
        start, end = mention.span.start, mention.span.end
        if any(start < other_end and other_start < end for other_start, other_end in seen):
            reasons.append(f"mention_overlap:{mention.id}")
        seen.append((start, end))
    return reasons


def relation_reach(goal: FormGoal) -> RelationReach:
    """Return the reach a goal's relation is read with.

    A scope names its group's whole membership, and a containment from that same group
    to its members only restates it, so such a relation is read with transitive reach.
    """

    relation = goal.relation
    if relation is None:
        return RelationReach.ONE_HOP
    scoped = any(
        item.role is FilterRole.SCOPE and item.mention == relation.anchor for item in goal.filters
    )
    return RelationReach.TRANSITIVE if scoped and _restates_scope(goal) else relation.reach


def _restates_scope(goal: FormGoal) -> bool:
    """Return whether a relation states exactly its scope group's whole membership.

    A scope reads every member of its group at any depth, so a transitive containment
    relation from that same group to its members names the same set and only restates it.
    """

    relation = goal.relation
    # A one-hop containment from the scope's own group also only restates that membership:
    # the compiler reads it as the scope's whole membership, the reading of "in the group".
    return (
        relation is not None
        and relation.anchor is not None
        and relation.sense is RelationSense.CONTAINMENT
        and relation.scope is RelationScope.ONE_SENSE
        and relation.anchor_position is SubjectPosition.SOURCE
        and goal.subject_scope is SubjectScope.COLLECTION
    )


def _goal_shape_failures(goal: FormGoal, form: SemanticQuestionForm) -> list[str]:
    failures: list[str] = []
    # A why question has one canonical reading, so no other goal can drop its cause atom.
    if (goal.operation is GoalOperation.EXPLAIN_CAUSE) != (goal.want is Want.CAUSE):
        failures.append(f"cause_form_inconsistent:{goal.id}")
    # A relation relates its results to another named thing, never a named subject to itself;
    # a reference to earlier rows may start its own read, so it is the one exception.
    if (
        goal.relation is not None
        and goal.subject is not None
        and goal.relation.anchor == goal.subject
        and goal.subject_scope is not SubjectScope.PRIOR_RESULT
    ):
        failures.append(f"relation_anchor_is_subject:{goal.id}")
    scopes = {item.mention for item in goal.filters if item.role is FilterRole.SCOPE}
    if (
        goal.relation is not None
        and (goal.relation.anchor or goal.subject) in scopes
        and not _restates_scope(goal)
    ):
        # A scope reads the group's whole membership, and a relation from the same group
        # reads its stated reach, so stating both leaves the answer undecided unless that
        # reach is the same whole membership.
        failures.append(f"scope_anchor_conflict:{goal.id}")
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

    An uncited declaration-kind mention is consumed by the form's schema goal, so it
    stands only when exactly one schema goal exists; with none it is unused, and with
    several its goal is ambiguous. The one reference mention of a prior-result goal
    without a subject is its subject. A mention that quotes exactly a goal's typed
    time cue restates that time expression, which the goal already reads.
    """

    cited = set(form.cited_mentions())
    time_cues = {
        (goal.time.cue.start, goal.time.cue.end)
        for goal in form.goals
        if goal.time.value is not None and goal.time.cue is not None
    }
    cited.update(
        mention.id
        for mention in form.mentions
        if (mention.span.start, mention.span.end) in time_cues
    )
    references = [mention.id for mention in form.mentions if mention.form in _REFERENCE_FORMS]
    if len(references) == 1 and any(
        goal.subject_scope is SubjectScope.PRIOR_RESULT and goal.subject is None
        for goal in form.goals
    ):
        cited.add(references[0])
    schema_goals = sum(goal.level is GoalLevel.SCHEMA for goal in form.goals)
    reasons: list[str] = []
    for mention in form.mentions:
        if mention.id in cited:
            continue
        if mention.domain is not MentionDomain.DECLARATION_KIND or schema_goals == 0:
            reasons.append(f"mention_unused:{mention.id}")
        elif schema_goals > 1:
            reasons.append(f"declaration_kind_goal_ambiguous:{mention.id}")
    return tuple(reasons)


def _relation_contradictions(form: SemanticQuestionForm) -> tuple[str, ...]:
    return tuple(
        f"relation_roles_inconsistent:{goal.id}"
        for goal in form.goals
        if goal.relation is not None and not goal.relation.roles_consistent
    )


__all__ = [
    "allowed_filter_domains",
    "DEFAULT_CONFIDENCE_FLOOR",
    "MAX_UNACCOUNTED_REASONS",
    "AdmissionDisposition",
    "FormAdmission",
    "SpanAccounting",
    "admit_question_form",
]
