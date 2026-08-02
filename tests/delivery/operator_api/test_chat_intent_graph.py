from __future__ import annotations

from collections.abc import Mapping

import pytest

from fdai.delivery.operator_api.routes.chat_intent_graph import (
    ActionPosture,
    BackendIntentGraphPlanner,
    EvidenceMode,
    parse_intent_graph,
    planner_context_envelope,
)
from fdai.delivery.operator_api.routes.chat_turn_plan import TurnTool


class _StructuredBackend:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.call: dict[str, object] = {}

    async def complete_structured(self, **kwargs: object) -> dict[str, object]:
        self.call = dict(kwargs)
        return self.result


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


@pytest.mark.asyncio
async def test_backend_planner_sends_strict_graph_schema_and_capabilities() -> None:
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
    backend = _StructuredBackend(raw)

    graph = await BackendIntentGraphPlanner(backend).plan_turn(
        prompt="상태를 확인하고 외부 기준과 비교해줘",
        tools=_tools(),
        history=({"role": "user", "content": "current dashboard"},),
    )

    assert graph.goals[1].depends_on == ("health",)
    assert backend.call["schema_name"] == "fdai_intent_graph_v2"
    assert backend.call["max_tokens"] == 1536
    schema = backend.call["schema"]
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False
    goal_schema = schema["properties"]["goals"]["items"]
    assert goal_schema["additionalProperties"] is False
    assert set(goal_schema["properties"]["capability"]["enum"]) == {
        "query_subscription_health",
        "web_search",
        "ops.restart-service",
        None,
    }
    user_content = str(backend.call["user_content"])
    assert "상태를 확인하고 외부 기준과 비교해줘" in user_content
    assert "query_subscription_health" in user_content


@pytest.mark.asyncio
async def test_backend_planner_projects_validated_images_into_intent_input() -> None:
    backend = _StructuredBackend(
        _graph(
            _goal(
                "diagnose_image",
                capability=None,
                evidence_mode="model_knowledge",
                intent="diagnosis",
            )
        )
    )

    await BackendIntentGraphPlanner(backend).plan_turn_with_context(
        prompt="Analyze the attached service diagram.",
        tools=_tools(),
        history=(),
        attachments=[
            {
                "name": "diagram.png",
                "media_type": "image/png",
                "data_url": "data:image/png;base64,cG5n",
                "byte_size": 3,
            }
        ],
    )

    content = backend.call["user_content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "Analyze the attached service diagram." in content[0]["text"]
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,cG5n"},
    }


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


def test_model_knowledge_cannot_satisfy_freshness_requirement() -> None:
    raw_goal = _goal(
        "latest",
        capability=None,
        evidence_mode="model_knowledge",
        intent="status",
    )
    raw_goal["freshness_required"] = True

    with pytest.raises(ValueError, match="fresh evidence"):
        parse_intent_graph(_graph(raw_goal), tools=_tools())


def test_planner_context_envelope_is_bounded_and_allowlisted() -> None:
    envelope = planner_context_envelope(
        {
            "routeId": "resilience",
            "routeLabel": "Resilience",
            "headline": "MTTR is 12 minutes",
            "capturedAt": "2026-08-02T03:00:00Z",
            "facts": [
                {
                    "key": "mttr",
                    "label": "Mean time to recovery",
                    "value": 12,
                    "unit": "minutes",
                    "window": "24h",
                    "observedAt": "2026-08-02T03:00:00Z",
                    "ignored": "not projected",
                }
            ],
            "explanations": {
                "selection": {
                    "entity_kind": "service",
                    "entity_id": "checkout-api",
                    "label": "Checkout API",
                }
            },
            "records": {"incidents": [{"secret": "must-not-leak"}]},
            "_user": {"name": "must-not-leak"},
            "_attachments": [
                {
                    "name": "topology.png",
                    "media_type": "image/png",
                    "byte_size": 42,
                    "data_url": "data:image/png;base64,c2VjcmV0",
                }
            ],
        },
        resource_context={
            "name": "checkout-api",
            "resource_type": "container_app",
            "evidence_ref": "inventory:checkout-api",
            "resource_group": "not-projected",
        },
        conversation_context={
            "kind": "incident",
            "incident_id": "INC-42",
            "selected_agent": "Heimdall",
            "private": "not-projected",
        },
    )

    assert envelope["authority"] == "selector_hint"
    screen = envelope["screen"]
    assert isinstance(screen, dict)
    assert screen["facts"][0] == {
        "key": "mttr",
        "value": 12,
        "label": "Mean time to recovery",
        "unit": "minutes",
        "window": "24h",
        "observedAt": "2026-08-02T03:00:00Z",
    }
    assert screen["selection"]["entity_id"] == "checkout-api"
    assert envelope["attachments"] == [
        {"name": "topology.png", "media_type": "image/png", "byte_size": 42}
    ]
    serialized = str(envelope)
    assert "must-not-leak" not in serialized
    assert "data:image" not in serialized
    assert "not-projected" not in serialized


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


def test_graph_allows_repeated_read_capability_with_distinct_arguments() -> None:
    graph = parse_intent_graph(
        _graph(
            _goal(
                "current",
                capability="query_subscription_health",
                arguments={"lookback_seconds": 3600},
            ),
            _goal(
                "baseline",
                capability="query_subscription_health",
                arguments={"lookback_seconds": 7200},
            ),
        ),
        tools=_tools(),
    )

    assert [goal.arguments["lookback_seconds"] for goal in graph.goals] == [3600, 7200]


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
    assert graph.confirmation_payload(request_id="request-1", session_id="session-1") == {
        "action_type": "ops.restart-service",
        "arguments": {"resource_ref": "service-example"},
        "session_id": "session-1",
        "idempotency_key": "draft-request-1",
    }


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
