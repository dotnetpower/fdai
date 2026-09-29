"""Blind reader majority for relation direction.

A reversed relation answers the opposite question, and open-ended extraction named
relation starts too rarely to catch a reversal. So each admitted goal whose relation
has a direction gets one focused, closed question to another model family: the
question text, the named start, the relation sense, and that sense's two roles in the
fixed order the ontology declares them. The reader never learns which role the proposer
chose. Core compares the chosen role with the form's. When a clear reading differs, a
third blind reader of another family answers the same closed question, and two of the
three readings decide: the form stands, or its two roles swap to the readers' reading.
An unclear or missing reading, or three different readings, hold the turn, and no code
interprets any word.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .semantic_reasoning_form import (
    SENSE_ROLES,
    RelationScope,
    RelationSense,
    SemanticQuestionForm,
    SubjectRole,
)
from .semantic_reasoning_relations import RECIPROCAL_TRAIT, SENSE_TRAITS

MAX_DIRECTION_QUESTIONS = 4
_READINGS = ("first", "second", "either", "unclear")


@dataclass(frozen=True, slots=True)
class DirectionQuestion:
    """One relation to confirm; ``stated`` stays in Core and is never sent to the reader."""

    goal_id: str
    anchor: str
    sense: RelationSense
    first: SubjectRole
    second: SubjectRole
    stated: SubjectRole
    # Whether a reciprocal LinkType of the sense is read on both sides anyway.
    mutual: bool = False

    def payload(self) -> dict[str, Any]:
        """Return the reader's input: the named start, the sense, and both roles in order."""

        return {
            "anchor": self.anchor,
            "sense": self.sense.value,
            "first": self.first.value,
            "second": self.second.value,
        }


def direction_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["reading"],
        "properties": {"reading": {"type": "string", "enum": list(_READINGS)}},
    }


def direction_questions(
    forms: Sequence[SemanticQuestionForm],
    *,
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[DirectionQuestion, ...]:
    """Return one question per goal whose relation has a direction to confirm.

    A relation stated as either has no direction, and one over every kind of relation
    reads each LinkType it reaches. A sense whose every declared LinkType is reciprocal,
    such as peering, is read on both sides whatever roles are stated, so its direction
    cannot change the answer.
    """

    directional = _senses(descriptors, reciprocal=False)
    mutual = _senses(descriptors, reciprocal=True)
    questions: list[DirectionQuestion] = []
    for form in forms:
        for goal in form.goals:
            relation = goal.relation
            if relation is None or relation.anchor_role is SubjectRole.EITHER:
                continue
            if relation.scope is RelationScope.ALL_KINDS:
                continue
            if relation.sense not in directional:
                continue
            start = relation.anchor if relation.anchor is not None else goal.subject
            if start is None:
                continue
            span = form.mention(start).span
            first, second = SENSE_ROLES[relation.sense]
            questions.append(
                DirectionQuestion(
                    goal_id=goal.id,
                    anchor=utterance[span.start : span.end],
                    sense=relation.sense,
                    first=first,
                    second=second,
                    stated=relation.anchor_role,
                    mutual=relation.sense in mutual,
                )
            )
    return tuple(questions[:MAX_DIRECTION_QUESTIONS])


def direction_reasons(
    questions: Sequence[DirectionQuestion],
    answers: Sequence[Mapping[str, Any] | None],
) -> tuple[str, ...]:
    """Return a hold reason for every question the reader does not confirm."""

    if len(questions) != len(answers):
        raise ValueError("direction answers MUST cover every direction question")
    reasons: list[str] = []
    for question, answer in zip(questions, answers, strict=True):
        role = _reading_role(question, answer)
        if isinstance(role, SubjectRole):
            if role is not question.stated:
                reasons.append(f"review_direction_differs:{question.goal_id}")
        elif role is not None:
            reasons.append(f"{role}:{question.goal_id}")
    return tuple(reasons)


DirectionCheck = Callable[["DirectionQuestion", bool], Awaitable[Mapping[str, Any] | None]]


@dataclass(frozen=True, slots=True)
class DirectionSettlement:
    """The form whose directions two agreeing readings decide, or the hold reasons."""

    form: SemanticQuestionForm
    reasons: tuple[str, ...] = ()
    # Goals whose two roles now follow two blind readers that outvoted the proposer.
    swapped: tuple[str, ...] = ()
    calls: int = 0


async def settle_directions(
    form: SemanticQuestionForm,
    *,
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
    check: DirectionCheck,
) -> DirectionSettlement:
    """Decide each directional relation by two agreeing readings of three at most.

    The first blind reader confirms or disputes the proposer's role. Only a clear
    dispute asks one more blind reader of another family, with ``True`` as the second
    argument of ``check``; its reading sides with one of the two. The proposer's form is
    never shown to either reader, and code compares closed roles only.
    """

    questions = direction_questions((form,), utterance=utterance, descriptors=descriptors)
    if not questions:
        return DirectionSettlement(form)
    first = await asyncio.gather(
        *(check(question, False) for question in questions), return_exceptions=True
    )
    reasons: list[str] = []
    disputed: list[tuple[DirectionQuestion, SubjectRole]] = []
    for question, answer in zip(questions, first, strict=True):
        role = _reading_role(question, answer if isinstance(answer, Mapping) else None)
        if isinstance(role, SubjectRole):
            if role is not question.stated:
                disputed.append((question, role))
        elif role is not None:
            reasons.append(f"{role}:{question.goal_id}")
    if reasons or not disputed:
        return DirectionSettlement(form, tuple(reasons), calls=len(questions))
    third = await asyncio.gather(
        *(check(question, True) for question, _role in disputed), return_exceptions=True
    )
    swaps: dict[str, SubjectRole] = {}
    for (question, role), answer in zip(disputed, third, strict=True):
        tiebreak = _reading_role(question, answer if isinstance(answer, Mapping) else None)
        # Only a concrete role joins a side; a mutual or unclear third reading decides nothing.
        if tiebreak is role:
            swaps[question.goal_id] = role
        elif tiebreak is not question.stated:
            reasons.append(f"review_direction_differs:{question.goal_id}")
    calls = len(questions) + len(disputed)
    if reasons:
        return DirectionSettlement(form, tuple(reasons), calls=calls)
    if not swaps:
        return DirectionSettlement(form, calls=calls)
    return DirectionSettlement(_swapped(form, swaps), swapped=tuple(sorted(swaps)), calls=calls)


def _reading_role(
    question: DirectionQuestion, answer: Mapping[str, Any] | None
) -> SubjectRole | str | None:
    """Return the anchor role one reading states, ``None`` when it leaves the stated
    direction standing, or the plain-string reason it cannot decide.

    ``SubjectRole`` is itself a string enum, so callers test for it first.
    """

    reading = answer.get("reading") if isinstance(answer, Mapping) else None
    if reading not in _READINGS:
        return "review_direction_unavailable"
    if reading == "unclear" or (reading == "either" and not question.mutual):
        return "review_direction_unclear"
    if reading == "either":
        # The reader finds the relation mutual, and its reciprocal LinkType is read on both
        # sides whatever role was stated.
        return None
    return question.first if reading == "first" else question.second


def _swapped(form: SemanticQuestionForm, swaps: Mapping[str, SubjectRole]) -> SemanticQuestionForm:
    """Return the form with each disputed goal's roles set to the agreeing readings."""

    goals = []
    for goal in form.goals:
        relation = goal.relation
        role = swaps.get(goal.id)
        if relation is None or role is None:
            goals.append(goal)
            continue
        first, second = SENSE_ROLES[relation.sense]
        result = second if role is first else first
        goals.append(
            goal.model_copy(
                update={
                    "relation": relation.model_copy(
                        update={"anchor_role": role, "result_role": result}
                    )
                }
            )
        )
    return SemanticQuestionForm.model_validate(
        form.model_copy(update={"goals": tuple(goals)}).model_dump(mode="json")
    )


def _senses(
    descriptors: Sequence[Mapping[str, Any]], *, reciprocal: bool
) -> frozenset[RelationSense]:
    """Return the senses with a declared LinkType that is, or is not, reciprocal."""

    senses: set[RelationSense] = set()
    for descriptor in descriptors:
        if descriptor.get("kind") != "link":
            continue
        traits = set(descriptor.get("semantic_traits") or ())
        if (RECIPROCAL_TRAIT in traits) is not reciprocal:
            continue
        senses.update(
            sense for sense, trait in SENSE_TRAITS.items() if trait is not None and trait in traits
        )
    return frozenset(senses)


__all__ = [
    "MAX_DIRECTION_QUESTIONS",
    "DirectionCheck",
    "DirectionQuestion",
    "DirectionSettlement",
    "direction_questions",
    "direction_reasons",
    "direction_schema",
    "settle_directions",
]
