"""One bounded repair of a proposed question form that breaks its contract.

A proposal that fails its closed schema or structural admission gets exactly one
more model call. The call presents the model's own rejected proposal and the
code-authored violations, and the model judges the correction. The repaired form
passes the same resolution and admission, and it must keep every operand, goal,
operation, typed time, and operand-bearing relation the rejected proposal stated:
a repair may restructure a form but never silently drop a stated constraint.
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
    if not repair_keeps_operands(raw, repaired.form, utterance=utterance):
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
) -> bool:
    """Return whether the repaired form keeps everything the rejected proposal stated.

    Every non-space character of each earlier mention quote, of any domain, must lie
    inside a repaired mention, so a repair may widen, split, trim, or relabel a
    mention but never shorten or delete it; only a mention that quoted exactly its
    goal's typed time cue may instead stay inside that goal's repaired time cue.
    Every earlier goal must survive with its operation, a typed time value must stay
    typed over at least its earlier cue, and a relation that carried an operand must
    stay over at least its earlier cue. A quote that no longer locates cannot be
    matched, so the repair must then keep at least as many mentions as before.
    """

    spans = [(mention.span.start, mention.span.end) for mention in repaired.mentions]
    times = [
        (goal.time.cue.start, goal.time.cue.end)
        for goal in repaired.goals
        if goal.time.value is not None and goal.time.cue is not None
    ]
    located, unlocated = _previous_mentions(previous, utterance)
    if unlocated and len(spans) < len(located) + unlocated:
        return False
    restated = _previous_time_cues(previous, utterance)
    if not all(
        _covered(quote, spans, utterance)
        or (quote in restated and _covered(quote, times, utterance))
        for quote in located
    ):
        return False
    goals = previous.get("goals")
    if not isinstance(goals, list):
        return True
    kept = {goal.id: goal for goal in repaired.goals}
    return all(
        _goal_kept(before, kept.get(str(before.get("id"))), utterance)
        for before in goals
        if isinstance(before, Mapping)
    )


def _goal_kept(before: Mapping[str, Any], after: FormGoal | None, utterance: str) -> bool:
    if after is None:
        return False
    operation = _enum(GoalOperation, before.get("operation"))
    if operation is not None and operation is not after.operation:
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
    return (
        relation.get("anchor") is not None
        or relation.get("counterpart") is not None
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


def _previous_time_cues(previous: Mapping[str, Any], utterance: str) -> set[tuple[int, int]]:
    goals = previous.get("goals")
    cues: set[tuple[int, int]] = set()
    for goal in goals if isinstance(goals, list) else ():
        time = goal.get("time") if isinstance(goal, Mapping) else None
        if isinstance(time, Mapping) and time.get("value") is not None:
            span = _locate(time.get("cue"), utterance)
            if span is not None:
                cues.add(span)
    return cues


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
