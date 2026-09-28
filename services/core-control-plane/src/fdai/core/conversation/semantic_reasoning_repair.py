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
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .semantic_reasoning_admission import AdmissionDisposition, FormAdmission, admit_question_form
from .semantic_reasoning_form import (
    FormGoal,
    GoalOperation,
    SemanticQuestionForm,
    SourceSpan,
    SubjectScope,
    Want,
)
from .semantic_reasoning_proposal import FormResolution, locate_quote, resolve_question_form

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
) -> FormProposal:
    """Resolve and admit one proposal, repairing a contract fault at most once."""

    raw = await propose()
    if raw is None:
        return FormProposal(None, None)
    resolution = resolve_question_form(raw, utterance=utterance)
    admission = _admit(resolution, utterance)
    repair = repair_for(raw, resolution, admission) if repairs > 0 else None
    if repair is None:
        return FormProposal(resolution, admission)
    faulted = resolution.reasons if admission is None else admission.reasons
    repaired_raw = await propose(repair=repair)
    if repaired_raw is None:
        return FormProposal(resolution, admission, "unavailable", faulted)
    repaired = resolve_question_form(repaired_raw, utterance=utterance)
    if repaired.form is None:
        return FormProposal(repaired, None, "invalid", faulted)
    if not repair_keeps_operands(raw, repaired.form, utterance=utterance, typed=resolution.form):
        return FormProposal(resolution, admission, "operand_dropped", faulted)
    return FormProposal(repaired, _admit(repaired, utterance), "applied", faulted)


def _admit(resolution: FormResolution, utterance: str) -> FormAdmission | None:
    if resolution.form is None:
        return None
    return admit_question_form(resolution.form, utterance=utterance)


def repair_for(
    raw: Mapping[str, Any],
    resolution: FormResolution,
    admission: FormAdmission | None,
) -> FormRepair | None:
    """Return the repair request for a contract fault, or None for any other outcome."""

    if resolution.form is None:
        violations = resolution.notes or resolution.reasons
    elif admission is not None and admission.disposition is AdmissionDisposition.INVALID:
        violations = admission.reasons
    else:
        return None
    if not violations:
        return None
    return FormRepair(previous=raw, violations=tuple(violations[:MAX_REPAIR_VIOLATIONS]))


def repair_keeps_operands(
    previous: Mapping[str, Any],
    repaired: SemanticQuestionForm,
    *,
    utterance: str,
    typed: SemanticQuestionForm | None = None,
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
    """

    if typed is None and not _raw_readable(previous):
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
]
