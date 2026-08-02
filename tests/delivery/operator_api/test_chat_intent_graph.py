from __future__ import annotations

from collections.abc import Mapping

import pytest

from fdai.delivery.operator_api.routes.chat_intent_graph import (
    ActionPosture,
    EvidenceMode,
    parse_intent_graph,
)
from fdai.delivery.operator_api.routes.chat_turn_plan import TurnTool


def _tools() -> tuple[TurnTool, ...]:
    return (
        TurnTool(
            name="query_subscription_health",
            description="Read bounded subscription health evidence.",
            side_effect_class="read",
            argument_schema={
                "type": "object",
                "properties": {
                    "lookback_seconds": {"type": "integer", "minimum": 60, "maximum": 86400},
                },
                "required": ["lookback_seconds"],
                "additionalProperties": False,
            },
        ),
        TurnTool(
            name="web_search",
            description="Search approved public domains.",
            side_effect_class="read",
            argument_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        TurnTool(
            name="ops.restart-service",
            description="Draft a restart request.",
            side_effect_class="write",
            argument_schema={
                "type": "object",
                "properties": {"resource_ref": {"type": "string", "minLength": 1}},
                "required": ["resource_ref"],
                "additionalProperties": False,
            },
        ),
    )


def _goal(
    goal_id: str,
    *,
    capability: str | None = None,
    arguments: Mapping[str, object] | None = None,
    depends_on: list[str] | None = None,
    evidence_mode: str = "operational",
    intent: str = "status",
) -> dict[str, object]:
    return {
        "goal_id": goal_id,
        "intent": intent,
        "capability": capability,
        "arguments": dict(arguments or {}),
        "depends_on": depends_on or [],
        "evidence_mode": evidence_mode,
        "freshness_required": evidence_mode in {"operational", "web", "mixed"},
        "confidence": 0.92,
        "alternatives": [],
    }


def _graph(
    *goals: dict[str, object],
    action_posture: str = "advise_only",
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "goals": list(goals),
        "clarification": None,
        "confidence": 0.91,
        "action_posture": action_posture,
    }


def test_compound_read_graph_preserves_goal_dependencies() -> None:
    raw = _graph(
        _goal(
            "health",
            capability="query_subscription_health",
            arguments={"lookback_seconds": 3600},
        ),
        _goal(
            "benchmark",
            capability="web_search",
            arguments={"query": "reliable service recovery benchmark"},
            depends_on=["health"],
            evidence_mode="web",
            intent="comparison",
        ),
    )

    graph = parse_intent_graph(raw, tools=_tools())

    assert graph.action_posture is ActionPosture.ADVISE_ONLY
    assert graph.goals[0].capability == "query_subscription_health"
    assert graph.goals[1].depends_on == ("health",)
    assert graph.goals[1].evidence_mode is EvidenceMode.WEB
    assert graph.to_dict() == raw


def test_model_knowledge_goal_needs_no_capability_or_arguments() -> None:
    graph = parse_intent_graph(
        _graph(
            _goal(
                "mythology",
                capability=None,
                evidence_mode="model_knowledge",
                intent="definition",
            )
        ),
        tools=_tools(),
    )

    assert graph.goals[0].capability is None


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (
            _graph(_goal("unknown", capability="query_unknown")),
            "unavailable capability",
        ),
        (
            _graph(
                _goal(
                    "invalid_args",
                    capability="query_subscription_health",
                    arguments={"lookback_seconds": 1},
                )
            ),
            "arguments are invalid",
        ),
        (
            _graph(
                _goal(
                    "first",
                    capability="query_subscription_health",
                    arguments={"lookback_seconds": 3600},
                    depends_on=["second"],
                ),
                _goal(
                    "second",
                    capability="web_search",
                    arguments={"query": "benchmark"},
                    depends_on=["first"],
                    evidence_mode="web",
                ),
            ),
            "dependency cycle",
        ),
        (
            _graph(
                _goal(
                    "first",
                    capability="query_subscription_health",
                    arguments={"lookback_seconds": 3600},
                ),
                _goal(
                    "second",
                    capability="query_subscription_health",
                    arguments={"lookback_seconds": 7200},
                ),
            ),
            "more than once",
        ),
        (
            _graph(
                _goal(
                    "restart",
                    capability="ops.restart-service",
                    arguments={"resource_ref": "service-example"},
                )
            ),
            "advise_only",
        ),
    ],
)
def test_invalid_graphs_fail_closed(raw: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_intent_graph(raw, tools=_tools())


def test_draft_only_allows_one_terminal_write_goal() -> None:
    graph = parse_intent_graph(
        _graph(
            _goal(
                "inspect",
                capability="query_subscription_health",
                arguments={"lookback_seconds": 3600},
            ),
            _goal(
                "restart",
                capability="ops.restart-service",
                arguments={"resource_ref": "service-example"},
                depends_on=["inspect"],
            ),
            action_posture="draft_only",
        ),
        tools=_tools(),
    )

    assert graph.requires_confirmation is True


def test_write_goal_cannot_feed_another_goal() -> None:
    raw = _graph(
        _goal(
            "restart",
            capability="ops.restart-service",
            arguments={"resource_ref": "service-example"},
        ),
        _goal(
            "inspect",
            capability="query_subscription_health",
            arguments={"lookback_seconds": 3600},
            depends_on=["restart"],
        ),
        action_posture="draft_only",
    )

    with pytest.raises(ValueError, match="terminal goal"):
        parse_intent_graph(raw, tools=_tools())
