"""Bounded multi-tool read planning through the conversation coordinator."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation import (
    AbstainResult,
    ConversationCoordinator,
    ConversationSession,
    Principal,
    Role,
    ToolResult,
    default_tool_schemas,
)
from fdai.core.conversation.tools import SideEffectClass


class _ReadTool:
    description = "Synthetic read tool."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, name: str, evidence_ref: str) -> None:
        self.name = name
        self.evidence_ref = evidence_ref
        self.calls: list[Mapping[str, object]] = []

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(
            status="ok",
            data={"tool": self.name, "arguments": dict(arguments)},
            preview=f"{self.name} complete",
            evidence_refs=(self.evidence_ref,),
        )


class _SimulateTool(_ReadTool):
    side_effect_class: SideEffectClass = "simulate"


class _FailingReadTool(_ReadTool):
    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        self.calls.append(arguments)
        raise ValueError("read provider rejected the query")


class _StateReadTool(_ReadTool):
    def __init__(
        self,
        name: str,
        evidence_ref: str,
        state: str,
        resource_id: str = "vm-example",
    ) -> None:
        super().__init__(name, evidence_ref)
        self.state = state
        self.resource_id = resource_id

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(
            status="ok",
            data={"resource_id": self.resource_id, "state": self.state},
            preview=f"{self.resource_id} state {self.state}",
            evidence_refs=(self.evidence_ref,),
        )


class _PlanningNarrator:
    def __init__(self, commands: tuple[str, ...]) -> None:
        self.commands = commands
        self.proposal_calls = 0
        self.render_calls = 0

    def propose_read_plan(self, **kwargs: Any) -> tuple[str, ...]:
        self.proposal_calls += 1
        return self.commands

    def translate(self, **kwargs: Any) -> None:
        return None

    def render_answer(self, *, tool: Any, result: ToolResult, **kwargs: Any) -> str:
        self.render_calls += 1
        assert tool.tool_name == "read_plan"
        assert [item["tool_name"] for item in result.data["results"]] == [
            "explore_catalog",
            "query_inventory",
        ]
        return "Catalog and inventory reads completed. [rule-example] [inventory:vm-example]"


def _session() -> ConversationSession:
    return ConversationSession(
        session_id="session-plan",
        principal=Principal(id="principal-example", role=Role.READER),
        channel_id="cli",
    )


def test_valid_read_plan_executes_and_aggregates_grounded_results() -> None:
    catalog = _ReadTool("explore_catalog", "rule-example")
    inventory = _ReadTool("query_inventory", "inventory:vm-example")
    narrator = _PlanningNarrator(("explore_catalog storage", "query_inventory virtual-machine"))
    coordinator = ConversationCoordinator(
        tools=(catalog, inventory),
        narrator=narrator,
        narrator_tool_schemas=default_tool_schemas(),
    )
    session = _session()

    result = coordinator.handle_turn(
        session=session,
        message="Compare storage catalog rules with virtual machine inventory.",
    )

    assert isinstance(result, ToolResult)
    assert result.status == "ok"
    assert result.evidence_refs == ("rule-example", "inventory:vm-example")
    assert result.preview.startswith("Catalog and inventory reads completed.")
    assert catalog.calls == [{"query": "storage"}]
    assert inventory.calls == [{"resource_type": "virtual-machine"}]
    assert narrator.render_calls == 1
    assert [turn.direction for turn in session.turns].count("tool_call") == 2
    assert [turn.direction for turn in session.turns].count("tool_result") == 2


def test_read_plan_with_non_read_step_executes_nothing() -> None:
    catalog = _ReadTool("explore_catalog", "rule-example")
    simulation = _SimulateTool("simulate_change", "audit:simulation-example")
    narrator = _PlanningNarrator(("explore_catalog storage", "simulate_change {}"))
    coordinator = ConversationCoordinator(
        tools=(catalog, simulation),
        narrator=narrator,
        narrator_tool_schemas=default_tool_schemas(),
    )

    result = coordinator.handle_turn(session=_session(), message="Do both checks.")

    assert isinstance(result, AbstainResult)
    assert catalog.calls == []
    assert simulation.calls == []
    assert narrator.render_calls == 0


def test_direct_t0_command_bypasses_read_planner() -> None:
    catalog = _ReadTool("explore_catalog", "rule-example")
    narrator = _PlanningNarrator(("explore_catalog one", "explore_catalog two"))
    coordinator = ConversationCoordinator(
        tools=(catalog,),
        narrator=narrator,
        narrator_tool_schemas=default_tool_schemas(),
    )

    result = coordinator.handle_turn(session=_session(), message="explore_catalog storage")

    assert isinstance(result, ToolResult)
    assert narrator.proposal_calls == 0
    assert catalog.calls == [{"query": "storage"}]


def test_failed_read_halts_remaining_plan_without_synthesis() -> None:
    catalog = _FailingReadTool("explore_catalog", "rule-example")
    inventory = _ReadTool("query_inventory", "inventory:vm-example")
    narrator = _PlanningNarrator(("explore_catalog storage", "query_inventory virtual-machine"))
    coordinator = ConversationCoordinator(
        tools=(catalog, inventory),
        narrator=narrator,
        narrator_tool_schemas=default_tool_schemas(),
    )

    result = coordinator.handle_turn(session=_session(), message="Compare both sources.")

    assert isinstance(result, ToolResult)
    assert result.status == "error"
    assert catalog.calls == [{"query": "storage"}]
    assert inventory.calls == []
    assert narrator.render_calls == 0


def test_conflicting_state_for_same_resource_blocks_synthesis() -> None:
    catalog = _StateReadTool("explore_catalog", "evidence-one", "healthy")
    inventory = _StateReadTool("query_inventory", "evidence-two", "unhealthy")
    narrator = _PlanningNarrator(("explore_catalog storage", "query_inventory virtual-machine"))
    coordinator = ConversationCoordinator(
        tools=(catalog, inventory),
        narrator=narrator,
        narrator_tool_schemas=default_tool_schemas(),
    )

    result = coordinator.handle_turn(session=_session(), message="Compare both sources.")

    assert isinstance(result, ToolResult)
    assert result.status == "abstain"
    assert result.data["conflicts"] == [
        {
            "identity_field": "resource_id",
            "identity": "vm-example",
            "field": "state",
            "values": ["healthy", "unhealthy"],
            "tools": ["explore_catalog", "query_inventory"],
        }
    ]
    assert result.evidence_refs == ("evidence-one", "evidence-two")
    assert narrator.render_calls == 0


def test_different_resource_states_do_not_create_false_conflict() -> None:
    catalog = _StateReadTool("explore_catalog", "evidence-one", "healthy", "vm-one")
    inventory = _StateReadTool("query_inventory", "evidence-two", "unhealthy", "vm-two")
    narrator = _PlanningNarrator(("explore_catalog storage", "query_inventory virtual-machine"))
    coordinator = ConversationCoordinator(
        tools=(catalog, inventory),
        narrator=narrator,
        narrator_tool_schemas=default_tool_schemas(),
    )

    result = coordinator.handle_turn(session=_session(), message="Compare both sources.")

    assert isinstance(result, ToolResult)
    assert result.status == "ok"
    assert "conflicts" not in result.data
    assert narrator.render_calls == 1
