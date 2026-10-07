"""One bounded repair of a proposed question form that breaks its contract.

A proposal that fails its closed schema or structural admission gets exactly one
more model call. The call presents the model's own rejected proposal and the
code-authored violations, and the model judges the correction. The repaired form
passes the same resolution and admission, and it must keep every operand, goal,
operation, want, typed time, operand-bearing relation, competing reading, and
pending-goals signal the rejected proposal stated: a repair may restructure a form
but never silently drop a stated constraint or the model's own caution.
Clarification and review outcomes are never repaired, because they are answers
to the operator rather than contract faults.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from .semantic_reasoning_admission import (
    AdmissionDisposition,
    FormAdmission,
    SpanAccounting,
    admit_question_form,
    allowed_filter_domains,
)
from .semantic_reasoning_form import (
    FilterRole,
    FormGoal,
    FormMention,
    GoalOperation,
    GroupBy,
    MentionDomain,
    MentionForm,
    SemanticQuestionForm,
    SourceSpan,
    SubjectScope,
    TimeKind,
    Want,
)
from .semantic_reasoning_proposal import FormResolution, locate_quote, resolve_question_form
from .semantic_reasoning_relabel import relabel_mentions

MAX_REPAIR_VIOLATIONS = 16


@dataclass(frozen=True, slots=True)
class FormRepair:
    """The model's own rejected proposal and the code-authored violations it must fix."""

    previous: Mapping[str, Any]
    violations: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {"previous_form": dict(self.previous), "violations": list(self.violations)}


@dataclass(frozen=True, slots=True)
class FormProposal:
    """The resolved and admitted proposal, and what one repair call did, if any.

    ``resolution`` is None only when the model returned no proposal at all.
    """

    resolution: FormResolution | None
    admission: FormAdmission | None
    repair: str | None = None
    repaired_reasons: tuple[str, ...] = ()


async def propose_with_repair(
    propose: Callable[..., Awaitable[Mapping[str, Any] | None]],
    *,
    utterance: str,
    repairs: int,
    accounting: SpanAccounting = SpanAccounting(),  # noqa: B008 - immutable value object
) -> FormProposal:
    """Resolve and admit one proposal, repairing a contract fault at most once."""

    raw = await propose()
    if raw is None:
        return FormProposal(None, None)
    resolution = resolve_question_form(raw, utterance=utterance)
    admission = _admit(resolution, utterance, accounting)
    repair = repair_for(raw, resolution, admission, utterance=utterance) if repairs > 0 else None
    if repair is None:
        return FormProposal(resolution, admission)
    faulted = resolution.reasons if admission is None else admission.reasons
    repaired_raw = await propose(repair=repair)
    if repaired_raw is None:
        return FormProposal(resolution, admission, "unavailable", faulted)
    repaired = resolve_question_form(repaired_raw, utterance=utterance)
    # A repair of unaccounted words only places them; it never rewrites stated meaning.
    placing = admission is not None and all(
        reason.startswith("span_unaccounted:") for reason in faulted
    )
    if repaired.form is None:
        return FormProposal(repaired, None, "invalid", faulted)
    form = repaired.form
    if resolution.form is not None:
        form = relabel_mentions(resolution.form, form)
        repaired = replace(repaired, form=form)
    if not repair_keeps_operands(
        raw, form, utterance=utterance, typed=resolution.form, extension_only=placing
    ):
        if placing and resolution.form is not None and same_reading(resolution.form, form):
            return _kept_original(resolution, utterance, faulted)
        return FormProposal(resolution, admission, "operand_dropped", faulted)
    admission = _admit(repaired, utterance, accounting)
    if (
        admission is not None
        and admission.disposition is AdmissionDisposition.INVALID
        and all(reason.startswith("span_unaccounted:") for reason in admission.reasons)
    ):
        # Accounting nudges the proposer once; after its repair, whether a leftover word
        # states a constraint is for the blind constraint review, which releases nothing
        # it cannot find stated.
        relaxed = _admit(repaired, utterance, SpanAccounting(required=False))
        return FormProposal(repaired, relaxed, "applied_unaccounted", faulted)
    return FormProposal(repaired, admission, "applied", faulted)


def same_reading(before: SemanticQuestionForm, after: SemanticQuestionForm) -> bool:
    """Return whether a repair reads every goal exactly as the proposal did.

    Only quotes may differ: every goal field other than its cue spans and confidence,
    the pending-goals signal, and the absence of competing readings must match, and
    the repair may declare no unsupported constraint the proposal lacked. A repair that
    asks a different question, such as a count for a list, is a competing reading.
    """

    return (
        _goal_readings(before) == _goal_readings(after)
        and before.remaining_goals == after.remaining_goals
        and not before.alternatives
        and not after.alternatives
        and set(after.unsupported_constraints) <= set(before.unsupported_constraints)
    )


def _goal_readings(form: SemanticQuestionForm) -> list[dict[str, Any]]:
    readings: list[dict[str, Any]] = []
    for goal in form.goals:
        reading = goal.model_dump(mode="json", exclude={"cue", "confidence"})
        for key in ("relation", "time", "measure"):
            nested = reading.get(key)
            if isinstance(nested, dict):
                nested.pop("cue", None)
                nested.pop("reach_cue", None)
                if isinstance(nested.get("order"), dict):
                    nested["order"].pop("cue", None)
                    nested["order"].pop("limit_span", None)
        for item in reading.get("filters") or ():
            item.pop("cue", None)
            item.pop("qualifier_span", None)
            if isinstance(item.get("comparison"), dict):
                for key in ("comparator_span", "value_span", "unit_span"):
                    item["comparison"].pop(key, None)
        readings.append(reading)
    return readings


def _kept_original(
    resolution: FormResolution, utterance: str, faulted: tuple[str, ...]
) -> FormProposal:
    """Keep a proposal whose only fault was accounting when its repair is unusable.

    The model was asked once to place its leftover words, and its repair read every
    goal the same way but changed a quote a placement may not change. The proposal
    then stands as it was, and whether a leftover word states a constraint is for the
    blind constraint review. A repair that reads a goal differently, or that does not
    parse, is a competing or missing reading, so the turn holds instead.
    """

    relaxed = _admit(resolution, utterance, SpanAccounting(required=False))
    return FormProposal(resolution, relaxed, "original_unaccounted", faulted)


def _admit(
    resolution: FormResolution, utterance: str, accounting: SpanAccounting
) -> FormAdmission | None:
    if resolution.form is None:
        return None
    return admit_question_form(resolution.form, utterance=utterance, accounting=accounting)


def repair_for(
    raw: Mapping[str, Any],
    resolution: FormResolution,
    admission: FormAdmission | None,
    *,
    utterance: str = "",
) -> FormRepair | None:
    """Return the repair request for a contract fault, or None for any other outcome.

    Recorded reasons stay content-free; only the violations shown to the model quote an
    unaccounted word, so the model can place it, and the adapter masks identifiers there.
    """

    if resolution.form is None:
        violations = resolution.notes or resolution.reasons
    elif admission is not None and admission.disposition is AdmissionDisposition.INVALID:
        quoted = frozenset(
            index
            for span in admission.form.declared_spans()
            for index in range(span.start, span.end)
        )
        # Runs of one wholly unquoted token render the same quote, so each appears once.
        violations = tuple(
            dict.fromkeys(_violation(reason, utterance, quoted) for reason in admission.reasons)
        )
    else:
        return None
    if not violations:
        return None
    return FormRepair(previous=raw, violations=tuple(violations[:MAX_REPAIR_VIOLATIONS]))


def _violation(reason: str, utterance: str, quoted: frozenset[int] = frozenset()) -> str:
    """Render one admission reason as a violation the model can act on.

    An unaccounted run is quoted so the model can place it; any other reason is stated
    as the contract rule it breaks, never as an interpretation of the question's words.
    ``quoted`` holds every character the form quotes, so a word with a quoted letter or
    digit is reported as partly quoted rather than as left out.
    """

    code, _, where = reason.partition(":")
    start_text, _, end_text = where.partition("-")
    if code != "span_unaccounted":
        return _explained(code, where) or reason
    if not start_text.isdigit() or not end_text.isdigit():
        return reason
    start, end = int(start_text), int(end_text)
    if end > len(utterance) or start >= end:
        return reason
    # Report the whole whitespace-delimited token, so a name or identifier reaches the
    # adapter's identifier mask intact instead of as an unmasked fragment.
    first, last = start, end
    while first > 0 and not utterance[first - 1].isspace():
        first -= 1
    while last < len(utterance) and not utterance[last].isspace():
        last += 1
    word = utterance[first:last]
    occurrence = 0
    position = -1
    while (position := utterance.find(word, position + 1)) != -1 and position <= first:
        occurrence += 1
    if not any(utterance[index].isalnum() and index in quoted for index in range(first, last)):
        return (
            f'span_unaccounted: the word "{word}" at occurrence {occurrence} is outside every '
            "mention, cue, and context quote"
        )
    # A quote already holds the rest of the word; the model is told which characters are
    # left by their place in it, so a fragment of a name is never quoted on its own.
    return (
        f'span_unaccounted: the word "{word}" at occurrence {occurrence} is only partly '
        f"quoted: {_characters(start - first, end - first, last - first)} outside every "
        "mention, cue, and context quote"
    )


def _characters(start: int, end: int, length: int) -> str:
    """Name a run of a word by its place: first, last, or 1-based character numbers."""

    count = end - start
    if start == 0:
        return "its first character is" if count == 1 else f"its first {count} characters are"
    if end == length:
        return "its last character is" if count == 1 else f"its last {count} characters are"
    if count == 1:
        return f"its character {start + 1} is"
    return f"its characters {start + 1} to {end} are"


def _explained(code: str, where: str) -> str | None:
    """Return the contract rule an admission reason breaks, or None to keep the code."""

    subject, _, role = where.partition(":")
    if code == "filter_domain" and role in {item.value for item in FilterRole}:
        filter_role = FilterRole(role)
        domains = ", ".join(
            item.value for item in allowed_filter_domains(filter_role, schema=False)
        )
        schema = ", ".join(item.value for item in allowed_filter_domains(filter_role, schema=True))
        return (
            f"filter_domain: goal {subject} has a {role} filter whose mention domain it cannot "
            f"take; an instance goal's {role} filter needs a mention with domain "
            f"{domains or 'none'}, and a schema goal's needs {schema or 'none'}"
        )
    rules = {
        "relation_anchor_missing": (
            "goal {0} has a relation with no named start; set relation.anchor to the mention "
            "of the named resource it starts from, or make that mention the goal subject"
        ),
        "relation_required": "goal {0} traverses but states no relation; add the relation",
        "measure_required": "goal {0} reads a measure but states none; add the measure",
        "anchor_missing": "goal {0} starts from a named thing but has no subject; set it",
        "relation_role_mismatch": (
            "the relation roles of goal {0} are not the two ends of its sense; use the two "
            "roles of that sense, or either for both"
        ),
        "collection_subject_domain": (
            "goal {0} ranges over a collection, so its subject must be a kind of thing: "
            "object_type, resource_type, or resource_class"
        ),
        "mention_unused": (
            "mention {0} is declared but nothing cites it; cite it from a goal, filter, or "
            "relation, or remove it"
        ),
        "mention_overlap": (
            "mention {0} shares words with an earlier mention; each word belongs to at most "
            "one mention, so quote each named thing on its own"
        ),
        "cause_form_inconsistent": (
            "goal {0} mixes a cause with another reading; a question about why something happened "
            "is operation explain_cause with want cause, and any other goal has want fact"
        ),
        "qualifier_not_instance": (
            "mention {0} has a qualifier, but a qualifier only places one named resource inside "
            "another named resource; state a kind or state of the results as a filter, and what "
            "they relate to as the goal's relation"
        ),
        "scope_anchor_conflict": (
            "goal {0} cites one group as both its scope filter and its relation anchor; keep "
            "only the scope filter, which covers members at any depth, or only the relation, "
            "which covers the reach it states"
        ),
    }
    rule = rules.get(code)
    return f"{code}: {rule.format(subject)}" if rule is not None and subject else None


def repair_keeps_operands(
    previous: Mapping[str, Any],
    repaired: SemanticQuestionForm,
    *,
    utterance: str,
    typed: SemanticQuestionForm | None = None,
    extension_only: bool = False,
    split: frozenset[str] = frozenset(),
) -> bool:
    """Return whether the repaired form keeps everything the rejected proposal stated.

    Every non-space character of each earlier mention quote, of any domain, must lie
    inside a repaired mention, so a repair may widen, split, trim, or relabel a
    mention but never shorten or delete it; only an uncited mention of a parsed
    proposal that quoted exactly a typed time cue may instead stay inside a repaired
    time cue.
    Every earlier goal must survive with its operation and want, a typed time value
    must stay typed over at least its earlier cue, and a relation that carried an
    operand must stay over at least its earlier cue. A competing reading must stay
    for each goal that had one, and pending goals must stay pending. A quote that no
    longer locates cannot be matched, so the repair must then keep at least as many
    mentions as before.

    ``typed`` is the rejected proposal as the closed schema read it, when it parsed.
    Operations, wants, competing readings, and pending goals then compare the typed
    values, because the schema normalizes raw values such as a numeric boolean. A
    proposal that never parsed has no typed reading, so every field compared here
    must keep its closed shape, any present pending-goals value other than false
    stays pending, and anything unreadable fails closed instead of counting as absent.

    ``split`` names typed mentions that an independent reading found merging separate
    constraints. The repair replaces each with narrower parts, so it is exempt from the
    extension and exact-key rules, and a goal may cite its parts where it cited it; its
    words must still lie inside repaired mentions.
    """

    if typed is None and not _raw_readable(previous):
        return False
    if split and typed is None:
        return False
    if extension_only and (typed is None or not _extends(typed, repaired, split)):
        return False
    if typed is not None and not _keys_kept(typed, repaired, split):
        return False
    spans = [(mention.span.start, mention.span.end) for mention in repaired.mentions]
    times = [
        (goal.time.cue.start, goal.time.cue.end)
        for goal in repaired.goals
        if goal.time.value is not None and goal.time.cue is not None
    ]
    located, unlocated = _previous_mentions(previous, utterance)
    if unlocated and len(spans) < len(located) + unlocated:
        return False
    restated = _restated_time_mentions(typed) if typed is not None else frozenset()
    if not all(
        _covered(quote, spans, utterance)
        or (quote in restated and _covered(quote, times, utterance))
        for quote in located
    ):
        return False
    goals = previous.get("goals")
    goals = goals if isinstance(goals, list) else []
    if not _caution(previous, goals, typed).kept_by(repaired):
        return False
    kept = {goal.id: goal for goal in repaired.goals}
    if typed is not None:
        stated = [goal for goal in goals if isinstance(goal, Mapping)]
        if len(stated) != len(typed.goals):
            return False
        return all(
            _meaning_kept(goal.operation, goal.want, kept.get(goal.id))
            and _cues_kept(before, kept.get(goal.id), utterance)
            for before, goal in zip(stated, typed.goals, strict=False)
        )
    for before in goals:
        if not isinstance(before, Mapping):
            continue
        after = kept.get(str(before.get("id")))
        operation = _enum(GoalOperation, before.get("operation"))
        want = Want.FACT if "want" not in before else _enum(Want, before.get("want"))
        if after is None or want is None or want is not after.want:
            return False
        if operation is None or operation is not after.operation:
            return False
        if not _cues_kept(before, after, utterance):
            return False
    return True


@dataclass(frozen=True, slots=True)
class _Caution:
    """The model's own caution in a rejected proposal: pending goals and competing readings."""

    pending: bool
    contested: bool
    contested_goals: frozenset[str]

    def kept_by(self, repaired: SemanticQuestionForm) -> bool:
        """Return whether the repaired form keeps every stated caution signal.

        A competing reading makes the form a clarification, so a repair that drops
        it would answer a question the model itself judged ambiguous.
        """

        if self.pending and not repaired.remaining_goals:
            return False
        if not self.contested:
            return True
        kept = {item.goal for item in repaired.alternatives}
        return bool(kept) and self.contested_goals <= kept


def _caution(
    previous: Mapping[str, Any], goals: list[Any], typed: SemanticQuestionForm | None
) -> _Caution:
    if typed is not None:
        return _Caution(
            pending=typed.remaining_goals,
            contested=bool(typed.alternatives),
            contested_goals=frozenset(item.goal for item in typed.alternatives),
        )
    alternatives = previous.get("alternatives")
    goal_ids = {
        goal["id"]
        for goal in goals
        if isinstance(goal, Mapping) and isinstance(goal.get("id"), str)
    }
    contested_goals = (
        frozenset(
            item["goal"]
            for item in alternatives
            if isinstance(item, Mapping)
            and isinstance(item.get("goal"), str)
            and item["goal"] in goal_ids
        )
        if isinstance(alternatives, list)
        else frozenset()
    )
    # Identity, not equality: a numeric zero is a stated value, not the schema's false.
    remaining = previous.get("remaining_goals")
    return _Caution(
        pending=remaining is not None and remaining is not False,
        contested=alternatives is not None
        and not (isinstance(alternatives, list) and not alternatives),
        contested_goals=contested_goals,
    )


def _keys_kept(
    typed: SemanticQuestionForm,
    repaired: SemanticQuestionForm,
    split: frozenset[str] = frozenset(),
) -> bool:
    """Return whether every exact lookup key of the proposal keeps its exact quote.

    An instance name or identifier binds by its exact characters, so widening it over a
    particle would look up a different name; a repair keeps such a quote as it was.
    """

    kept = {mention.id: mention.span for mention in repaired.mentions}
    return all(
        kept.get(mention.id) == mention.span
        for mention in typed.mentions
        if _is_lookup_key(mention) and mention.id not in split
    )


def _is_lookup_key(mention: FormMention) -> bool:
    return mention.domain is MentionDomain.INSTANCE and mention.form in {
        MentionForm.NAME,
        MentionForm.IDENTIFIER,
    }


def _extends(
    typed: SemanticQuestionForm,
    repaired: SemanticQuestionForm,
    split: frozenset[str] = frozenset(),
) -> bool:
    """Return whether a repair only adds information to what the proposal stated.

    Placing unaccounted words may add a mention, a goal, a filter, a cue's reach, or
    context, and may state a value the proposal left at its default, such as a subject,
    relation, measure, grouping, or time window. A stated value never changes or
    disappears: every mention keeps its id, form, domain, and qualifier within a span
    that may only widen, and every
    goal keeps its level, operation, scope, want, dependencies, and stated fields.
    """

    mentions = {mention.id: mention for mention in repaired.mentions}
    literal = typed.literal_mentions()
    if not all(
        (after := mentions.get(mention.id)) is not None
        and _widens(mention, after, literal=mention.id in literal)
        for mention in typed.mentions
        if mention.id not in split
    ):
        return False
    goals = {goal.id: goal for goal in repaired.goals}
    return all(
        (extended := goals.get(goal.id)) is not None and _goal_extends(goal, extended, split)
        for goal in typed.goals
    )


def _widens(before: FormMention, after: FormMention, *, literal: bool = False) -> bool:
    """Return whether a mention keeps its id, form, domain, and qualifier within a wider span.

    A literal operand's quote, such as a name fragment, is itself the value the query
    uses, so widening it would change the query rather than add information; it must
    stay exact.
    """

    if literal and after.span != before.span:
        return False
    return (
        (after.form, after.domain, after.qualifier)
        == (before.form, before.domain, before.qualifier)
        and after.span.start <= before.span.start
        and before.span.end <= after.span.end
    )


def _goal_extends(before: FormGoal, after: FormGoal, split: frozenset[str] = frozenset()) -> bool:
    """Return whether a goal keeps every stated value; a split mention's citations may move.

    Where the goal cited a mention being split, it may cite one of the parts instead, or
    a part may take another place; every other stated value stays as it was.
    """

    fixed = ("level", "operation", "subject_scope", "want", "depends_on")
    if any(getattr(before, name) != getattr(after, name) for name in fixed):
        return False
    if before.subject is not None and (
        after.subject is None if before.subject in split else before.subject != after.subject
    ):
        return False
    kept = {(item.role, item.mention) for item in after.filters}
    if not {(item.role, item.mention) for item in before.filters if item.mention not in split} <= (
        kept
    ):
        return False
    if before.relation is not None and (
        after.relation is None or not _relation_kept(before.relation, after.relation, split)
    ):
        return False
    if before.time.kind not in {TimeKind.CURRENT, TimeKind.UNSPECIFIED} and (
        _uncued(before.time) != _uncued(after.time)
    ):
        return False
    measure, repaired = before.measure, after.measure
    if measure is None:
        return True
    return (
        repaired is not None
        and repaired.kind is measure.kind
        and (measure.mention in {None, repaired.mention} or measure.mention in split)
        and measure.group_by in {GroupBy.NONE, repaired.group_by}
    )


def _uncued(value: BaseModel) -> dict[str, Any]:
    # Cues may widen or be added by a repair; the typed atoms they quote may not change.
    return value.model_dump(mode="json", exclude={"cue", "reach_cue"})


def _relation_kept(before: BaseModel, after: BaseModel, split: frozenset[str]) -> bool:
    """Return whether a relation keeps its typed atoms; a split end may cite a part."""

    stated, repaired = _uncued(before), _uncued(after)
    for key in ("anchor", "counterpart"):
        if stated.get(key) in split:
            stated.pop(key)
            repaired.pop(key, None)
    return stated == repaired


def _raw_readable(previous: Mapping[str, Any]) -> bool:
    """Return whether every field compared here keeps its closed shape in unparsed output.

    Mentions and goals must be lists of objects, goal ids unique text, operations and
    wants readable, and time and relation objects when present. A wrong container, a
    duplicate id, or an unreadable value cannot be compared, so it never counts as an
    absent constraint.
    """

    mentions = previous.get("mentions")
    # The schema reads omitted mentions as none, but never an explicit null or another shape.
    if "mentions" in previous and not _objects(mentions):
        return False
    goals = previous.get("goals")
    # Goals are required and non-empty, so a missing, null, or empty list is unreadable.
    if not _objects(goals) or not goals:
        return False
    ids = [goal.get("id") for goal in goals]
    if not all(isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        return False
    return all(_raw_goal_readable(goal) for goal in goals)


def _objects(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def _raw_goal_readable(goal: Mapping[str, Any]) -> bool:
    if _enum(GoalOperation, goal.get("operation")) is None:
        return False
    if "want" in goal and _enum(Want, goal["want"]) is None:
        return False
    return all(
        goal.get(field) is None or isinstance(goal.get(field), Mapping)
        for field in ("time", "relation")
    )


def _meaning_kept(operation: GoalOperation, want: Want, after: FormGoal | None) -> bool:
    return after is not None and after.operation is operation and after.want is want


def _cues_kept(before: Mapping[str, Any], after: FormGoal | None, utterance: str) -> bool:
    """Return whether a typed time and an operand-bearing relation keep their cues."""

    if after is None:
        return False
    time = before.get("time")
    if isinstance(time, Mapping) and time.get("value") is not None:
        if after.time.value is None or not _cue_kept(time.get("cue"), after.time.cue, utterance):
            return False
    relation = before.get("relation")
    if isinstance(relation, Mapping) and _carries_operand(before, relation):
        if after.relation is None or not _cue_kept(
            relation.get("cue"), after.relation.cue, utterance
        ):
            return False
    return True


def _carries_operand(goal: Mapping[str, Any], relation: Mapping[str, Any]) -> bool:
    scope = _enum(SubjectScope, goal.get("subject_scope"))
    # An unreadable subject scope may name an anchor, so its relation stays protected.
    return (
        relation.get("anchor") is not None
        or relation.get("counterpart") is not None
        or scope is None
        or scope is SubjectScope.ANCHOR
    )


def _cue_kept(before: object, after: SourceSpan | None, utterance: str) -> bool:
    if after is None:
        return False
    span = _locate(before, utterance)
    return span is None or _covered(span, [(after.start, after.end)], utterance)


def _previous_mentions(
    previous: Mapping[str, Any], utterance: str
) -> tuple[list[tuple[int, int]], int]:
    mentions = previous.get("mentions")
    if not isinstance(mentions, list):
        return [], 0
    located: list[tuple[int, int]] = []
    unlocated = 0
    for mention in mentions:
        if not isinstance(mention, Mapping):
            continue
        span = _locate(mention.get("span"), utterance)
        if span is None:
            unlocated += 1
        else:
            located.append(span)
    return located, unlocated


def _restated_time_mentions(typed: SemanticQuestionForm) -> frozenset[tuple[int, int]]:
    """Return the spans of uncited mentions that quote exactly a typed time cue.

    Only such a mention merely restates its goal's time, so only it may survive inside a
    repaired time cue instead of a repaired mention. The exemption needs the closed
    schema's reading: a proposal that never parsed has no validated time to restate, and
    a mention any goal cites is an operand, never a time restatement.
    """

    cues = {
        (goal.time.cue.start, goal.time.cue.end)
        for goal in typed.goals
        if goal.time.value is not None and goal.time.cue is not None
    }
    cited = typed.cited_mentions()
    return frozenset(
        (mention.span.start, mention.span.end)
        for mention in typed.mentions
        if mention.id not in cited and (mention.span.start, mention.span.end) in cues
    )


def _locate(quote: object, utterance: str) -> tuple[int, int] | None:
    if not isinstance(quote, Mapping):
        return None
    text = quote.get("text")
    occurrence = quote.get("occurrence", 1)
    if not isinstance(text, str) or type(occurrence) is not int:
        return None
    return locate_quote(text, occurrence, utterance)


def _enum[Member: StrEnum](kind: type[Member], value: object) -> Member | None:
    if not isinstance(value, str):
        return None
    try:
        return kind(value)
    except ValueError:
        return None


def _covered(quote: tuple[int, int], spans: list[tuple[int, int]], utterance: str) -> bool:
    """Return whether every non-space character of ``quote`` lies inside one of ``spans``."""

    return all(
        any(start <= index < end for start, end in spans)
        for index in range(*quote)
        if not utterance[index].isspace()
    )


__all__ = [
    "MAX_REPAIR_VIOLATIONS",
    "FormProposal",
    "FormRepair",
    "propose_with_repair",
    "repair_for",
    "repair_keeps_operands",
    "same_reading",
]
