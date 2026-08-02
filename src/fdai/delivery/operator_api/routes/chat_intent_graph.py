"""Validated hierarchical intent graphs for Operator API conversations."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from jsonschema import Draft202012Validator

from fdai.core.conversation.answer_plan import AnswerIntent
from fdai.delivery.operator_api.routes.chat_turn_plan import TurnTool


class ActionPosture(StrEnum):
    ADVISE_ONLY = "advise_only"
    DRAFT_ONLY = "draft_only"


class EvidenceMode(StrEnum):
    SCREEN = "screen"
    OPERATIONAL = "operational"
    WEB = "web"
    CATALOG = "catalog"
    MODEL_KNOWLEDGE = "model_knowledge"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class IntentGoal:
    goal_id: str
    intent: AnswerIntent
    capability: str | None
    arguments: Mapping[str, object]
    depends_on: tuple[str, ...]
    evidence_mode: EvidenceMode
    freshness_required: bool
    confidence: float
    alternatives: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntentGraph:
    schema_version: int
    goals: tuple[IntentGoal, ...]
    clarification: str | None
    confidence: float
    action_posture: ActionPosture

    @property
    def requires_confirmation(self) -> bool:
        return self.action_posture is ActionPosture.DRAFT_ONLY

    @property
    def primary_intent(self) -> AnswerIntent:
        return self.goals[0].intent

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "goals": [
                {
                    "goal_id": goal.goal_id,
                    "intent": goal.intent.value,
                    "capability": goal.capability,
                    "arguments": dict(goal.arguments),
                    "depends_on": list(goal.depends_on),
                    "evidence_mode": goal.evidence_mode.value,
                    "freshness_required": goal.freshness_required,
                    "confidence": goal.confidence,
                    "alternatives": list(goal.alternatives),
                }
                for goal in self.goals
            ],
            "clarification": self.clarification,
            "confidence": self.confidence,
            "action_posture": self.action_posture.value,
        }


_VERSION: Final = 2
_MAX_GOALS: Final = 8
_GOAL_ID: Final = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_GRAPH_FIELDS: Final = {"schema_version", "goals", "clarification", "confidence", "action_posture"}
_GOAL_FIELDS: Final = {
    "goal_id",
    "intent",
    "capability",
    "arguments",
    "depends_on",
    "evidence_mode",
    "freshness_required",
    "confidence",
    "alternatives",
}


def parse_intent_graph(raw: Mapping[str, object], *, tools: Sequence[TurnTool]) -> IntentGraph:
    """Validate an untrusted graph against the available capability manifest."""
    if set(raw) != _GRAPH_FIELDS or raw.get("schema_version") != _VERSION:
        raise ValueError("intent graph fields or schema version are invalid")
    raw_goals = raw.get("goals")
    if not isinstance(raw_goals, list) or not 1 <= len(raw_goals) <= _MAX_GOALS:
        raise ValueError("intent graph goals are invalid")
    try:
        posture = ActionPosture(str(raw["action_posture"]))
    except ValueError as exc:
        raise ValueError("intent graph action posture is invalid") from exc
    by_name = {tool.name: tool for tool in tools}
    goals = tuple(_parse_goal(item, by_name) for item in raw_goals)
    _validate_dag(goals)
    _validate_authority(goals, by_name, posture)
    return IntentGraph(
        schema_version=_VERSION,
        goals=goals,
        clarification=_optional_text(raw.get("clarification"), 512),
        confidence=_confidence(raw.get("confidence"), "graph"),
        action_posture=posture,
    )


def _parse_goal(raw: object, by_name: Mapping[str, TurnTool]) -> IntentGoal:
    if not isinstance(raw, Mapping) or set(raw) != _GOAL_FIELDS:
        raise ValueError("intent graph goal fields are invalid")
    goal_id = raw.get("goal_id")
    if not isinstance(goal_id, str) or _GOAL_ID.fullmatch(goal_id) is None:
        raise ValueError("intent graph goal id is invalid")
    try:
        intent = AnswerIntent(str(raw["intent"]))
        evidence_mode = EvidenceMode(str(raw["evidence_mode"]))
    except ValueError as exc:
        raise ValueError("intent graph goal enum is invalid") from exc
    capability = _optional_text(raw.get("capability"), 128)
    arguments = raw.get("arguments")
    if not isinstance(arguments, Mapping) or any(not isinstance(key, str) for key in arguments):
        raise ValueError("intent graph goal arguments are invalid")
    normalized = {key: value for key, value in arguments.items() if value is not None}
    dependencies = _strings(raw.get("depends_on"), 7, "dependencies")
    alternatives = _strings(raw.get("alternatives"), 4, "alternatives")
    freshness = raw.get("freshness_required")
    if not isinstance(freshness, bool):
        raise ValueError("intent graph freshness requirement is invalid")
    if capability is None:
        if normalized or evidence_mode not in {
            EvidenceMode.SCREEN,
            EvidenceMode.CATALOG,
            EvidenceMode.MODEL_KNOWLEDGE,
        }:
            raise ValueError("intent graph presentation goal is invalid")
    else:
        tool = by_name.get(capability)
        if tool is None:
            raise ValueError("intent graph selected an unavailable capability")
        if any(Draft202012Validator(dict(tool.argument_schema)).iter_errors(normalized)):
            raise ValueError("intent graph capability arguments are invalid")
    if any(item not in by_name for item in alternatives):
        raise ValueError("intent graph alternative capability is unavailable")
    return IntentGoal(
        goal_id=goal_id,
        intent=intent,
        capability=capability,
        arguments=normalized,
        depends_on=dependencies,
        evidence_mode=evidence_mode,
        freshness_required=freshness,
        confidence=_confidence(raw.get("confidence"), "goal"),
        alternatives=alternatives,
    )


def _validate_dag(goals: Sequence[IntentGoal]) -> None:
    by_id = {goal.goal_id: goal for goal in goals}
    if len(by_id) != len(goals):
        raise ValueError("intent graph goal ids must be unique")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(goal_id: str) -> None:
        if goal_id in visiting:
            raise ValueError("intent graph contains a dependency cycle")
        if goal_id in visited:
            return
        visiting.add(goal_id)
        for dependency in by_id[goal_id].depends_on:
            if dependency not in by_id or dependency == goal_id:
                raise ValueError("intent graph dependencies are invalid")
            visit(dependency)
        visiting.remove(goal_id)
        visited.add(goal_id)

    for goal in goals:
        visit(goal.goal_id)


def _validate_authority(
    goals: Sequence[IntentGoal],
    by_name: Mapping[str, TurnTool],
    posture: ActionPosture,
) -> None:
    selected = [by_name[goal.capability] for goal in goals if goal.capability is not None]
    if len({tool.name for tool in selected}) != len(selected):
        raise ValueError("intent graph cannot select one capability more than once")
    writes = [
        goal
        for goal in goals
        if goal.capability is not None and by_name[goal.capability].side_effect_class != "read"
    ]
    if posture is ActionPosture.ADVISE_ONLY and writes:
        raise ValueError("intent graph advise_only cannot select a write capability")
    if posture is ActionPosture.DRAFT_ONLY:
        if len(writes) != 1:
            raise ValueError("intent graph draft_only requires exactly one write capability")
        if any(writes[0].goal_id in goal.depends_on for goal in goals):
            raise ValueError("intent graph write draft must be a terminal goal")


def _optional_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("intent graph text field is invalid")
    return value.strip()


def _confidence(value: object, field: str) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"intent graph {field} confidence is invalid")
    return float(value)


def _strings(value: object, maximum: int, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"intent graph {field} are invalid")
    items = tuple(value)
    if any(not isinstance(item, str) or not item or len(item) > 128 for item in items):
        raise ValueError(f"intent graph {field} are invalid")
    if len(set(items)) != len(items):
        raise ValueError(f"intent graph {field} must be unique")
    return items


__all__ = ["ActionPosture", "EvidenceMode", "IntentGoal", "IntentGraph", "parse_intent_graph"]
