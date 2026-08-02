from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.routes.chat_intent_graph import parse_intent_graph
from fdai.delivery.operator_api.routes.chat_intent_graph_execution import (
    resolve_intent_graph_evidence,
)
from fdai.delivery.operator_api.routes.chat_turn_plan import TurnTool


class _Tools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> Mapping[str, Any] | None:
        self.calls.append(tool_name)
        if tool_name == "query_unavailable":
            return None
        return {
            "tool": tool_name,
            "authority": "server_read_model",
            "result": {"arguments": dict(arguments), "principal": principal_id},
        }


class _Web:
    async def resolve_planned(
        self,
        arguments: Mapping[str, object],
        view_context: Mapping[str, Any],
        *,
        progress_observer: Any = None,
    ) -> Mapping[str, Any] | None:
        assert progress_observer is not None
        return {
            "status": "matched",
            "query": arguments["query"],
            "context_keys": sorted(view_context),
        }


class _UnavailableWeb:
    async def resolve_planned(
        self,
        arguments: Mapping[str, object],
        view_context: Mapping[str, Any],
        *,
        progress_observer: Any = None,
    ) -> Mapping[str, Any] | None:
        del arguments, view_context, progress_observer
        return {"status": "unavailable", "reason": "provider_unavailable", "sources": []}


def _tools() -> tuple[TurnTool, ...]:
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    return (
        TurnTool("query_health", "Read health.", "read", schema),
        TurnTool("query_unavailable", "Unavailable read.", "read", schema),
        TurnTool("ops.restart", "Draft a restart.", "write", schema),
        TurnTool(
            "web_search",
            "Search public web.",
            "read",
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
    )


def _goal(
    goal_id: str,
    capability: str | None,
    *,
    depends_on: list[str] | None = None,
    arguments: Mapping[str, object] | None = None,
    evidence_mode: str = "operational",
    freshness_required: bool | None = None,
) -> dict[str, object]:
    return {
        "goal_id": goal_id,
        "intent": "status",
        "capability": capability,
        "arguments": dict(arguments or {}),
        "depends_on": depends_on or [],
        "evidence_mode": evidence_mode,
        "freshness_required": (
            evidence_mode in {"operational", "web", "mixed"}
            if freshness_required is None
            else freshness_required
        ),
        "confidence": 0.9,
        "alternatives": [],
    }


def _graph(*goals: dict[str, object], action_posture: str = "advise_only"):
    return parse_intent_graph(
        {
            "schema_version": 2,
            "goals": list(goals),
            "clarification": None,
            "confidence": 0.9,
            "action_posture": action_posture,
        },
        tools=_tools(),
    )


async def test_graph_executor_preserves_dependency_order_and_all_evidence() -> None:
    resolver = _Tools()
    events: list[Mapping[str, Any]] = []

    async def observe(event: Mapping[str, Any]) -> None:
        events.append(event)

    graph = _graph(
        _goal("health", "query_health"),
        _goal(
            "benchmark",
            "web_search",
            depends_on=["health"],
            arguments={"query": "service recovery benchmark"},
            evidence_mode="web",
        ),
    )

    result = await resolve_intent_graph_evidence(
        request_id="request-1",
        prompt="check health and compare it",
        graph=graph,
        view_context={"routeId": "overview"},
        user_id="reader",
        session_id="session-1",
        planned_tool_resolver=resolver,
        agent_delegate=None,
        web_search_resolver=_Web(),
        progress_observer=observe,
    )

    ledger = result["_intent_graph_evidence"]
    assert ledger["status"] == "completed"
    assert ledger["evidence_mode"] == "mixed_grounded"
    assert [goal["goal_id"] for goal in ledger["goals"]] == ["health", "benchmark"]
    assert [goal["task_id"] for goal in ledger["goals"]] == [
        "request-1:health",
        "request-1:benchmark",
    ]
    assert all(goal["started_at"].endswith("+00:00") for goal in ledger["goals"])
    assert all(goal["completed_at"].endswith("+00:00") for goal in ledger["goals"])
    assert resolver.calls == ["query_health"]
    assert result["_tool_evidence"]["tool"] == "query_health"
    assert result["_web_evidence"]["status"] == "matched"
    terminal_ids = [event["branch_id"] for event in events if event["status"] == "completed"]
    assert terminal_ids == ["request-1:health", "request-1:benchmark"]


async def test_graph_executor_reports_partial_without_dropping_success() -> None:
    resolver = _Tools()
    graph = _graph(
        _goal("health", "query_health"),
        _goal("missing", "query_unavailable"),
        _goal("knowledge", None, evidence_mode="model_knowledge"),
    )

    result = await resolve_intent_graph_evidence(
        request_id="request-2",
        prompt="compound question",
        graph=graph,
        view_context={},
        user_id="reader",
        session_id="session-2",
        planned_tool_resolver=resolver,
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=lambda _event: _completed(),
    )

    ledger = result["_intent_graph_evidence"]
    assert ledger["status"] == "partial"
    assert ledger["evidence_mode"] == "partial"
    assert [goal["status"] for goal in ledger["goals"]] == [
        "completed",
        "unavailable",
        "completed",
    ]
    assert result["_tool_evidence"]["tool"] == "query_health"
    assert ledger["goals"][1]["reason"] == "capability_unavailable"
    assert ledger["goals"][2]["evidence"]["authority"] == "model_knowledge"


async def test_graph_executor_skips_goal_with_unsuccessful_dependency() -> None:
    resolver = _Tools()
    events: list[Mapping[str, Any]] = []

    async def observe(event: Mapping[str, Any]) -> None:
        events.append(event)

    graph = _graph(
        _goal("missing", "query_unavailable"),
        _goal("dependent", "query_health", depends_on=["missing"]),
    )

    result = await resolve_intent_graph_evidence(
        request_id="request-3",
        prompt="use the first result in the second query",
        graph=graph,
        view_context={},
        user_id="reader",
        session_id="session-3",
        planned_tool_resolver=resolver,
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=observe,
    )

    goals = result["_intent_graph_evidence"]["goals"]
    assert resolver.calls == ["query_unavailable"]
    assert goals[1]["status"] == "skipped"
    assert goals[1]["reason"] == "dependency_not_completed"
    assert goals[1]["blocked_by"] == ["missing"]
    assert events[-1]["status"] == "unavailable"


async def test_graph_executor_runs_repeated_capability_for_each_goal() -> None:
    resolver = _Tools()
    graph = _graph(
        _goal("first", "query_health"),
        _goal("second", "query_health"),
    )

    result = await resolve_intent_graph_evidence(
        request_id="request-4",
        prompt="compare two health scopes",
        graph=graph,
        view_context={},
        user_id="reader",
        session_id="session-4",
        planned_tool_resolver=resolver,
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=lambda _event: _completed(),
    )

    assert resolver.calls == ["query_health", "query_health"]
    assert [goal["status"] for goal in result["_intent_graph_evidence"]["goals"]] == [
        "completed",
        "completed",
    ]


async def test_graph_executor_never_dispatches_write_goal() -> None:
    resolver = _Tools()
    graph = _graph(
        _goal("restart", "ops.restart"),
        action_posture="draft_only",
    )

    result = await resolve_intent_graph_evidence(
        request_id="request-5",
        prompt="restart the service",
        graph=graph,
        view_context={},
        user_id="reader",
        session_id="session-5",
        planned_tool_resolver=resolver,
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=lambda _event: _completed(),
    )

    receipt = result["_intent_graph_evidence"]["goals"][0]
    assert resolver.calls == []
    assert receipt["status"] == "skipped"
    assert receipt["reason"] == "write_execution_forbidden"


async def test_nonfresh_web_goal_falls_back_to_labeled_model_knowledge() -> None:
    graph = _graph(
        _goal(
            "mythology",
            "web_search",
            arguments={"query": "Bragi mythology"},
            evidence_mode="web",
            freshness_required=False,
        )
    )

    result = await resolve_intent_graph_evidence(
        request_id="request-6",
        prompt="Who is Bragi in mythology?",
        graph=graph,
        view_context={},
        user_id="reader",
        session_id="session-6",
        planned_tool_resolver=None,
        agent_delegate=None,
        web_search_resolver=_UnavailableWeb(),
        progress_observer=lambda _event: _completed(),
    )

    ledger = result["_intent_graph_evidence"]
    assert ledger["status"] == "completed"
    assert ledger["evidence_mode"] == "model_knowledge"
    assert ledger["goals"][0]["reason"] == "web_unavailable_model_knowledge_fallback"
    assert ledger["goals"][0]["evidence"]["authority"] == "model_knowledge"
    assert "_web_evidence" not in result


async def test_fresh_web_goal_stays_unavailable_without_model_fallback() -> None:
    graph = _graph(
        _goal(
            "latest",
            "web_search",
            arguments={"query": "latest recovery benchmark"},
            evidence_mode="web",
            freshness_required=True,
        )
    )

    result = await resolve_intent_graph_evidence(
        request_id="request-7",
        prompt="What is the latest recovery benchmark?",
        graph=graph,
        view_context={},
        user_id="reader",
        session_id="session-7",
        planned_tool_resolver=None,
        agent_delegate=None,
        web_search_resolver=_UnavailableWeb(),
        progress_observer=lambda _event: _completed(),
    )

    ledger = result["_intent_graph_evidence"]
    assert ledger["status"] == "unavailable"
    assert ledger["evidence_mode"] == "held_for_review"
    assert ledger["goals"][0]["status"] == "unavailable"


async def _completed() -> None:
    return None
