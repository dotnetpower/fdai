"""Conversation-port helpers for :class:`PantheonRuntime`.

The composition root owns wiring; this module keeps Bragi-facing delegation
methods out of the runtime file without changing the public runtime API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.agents._framework.conversation_tools import AgentConversationToolRegistry, AgentToolResult
from fdai.agents._framework.tool_planner import (
    MAX_TOOL_PLANS,
    ConversationToolPlan,
    plan_conversation_tools,
)
from fdai.agents._framework.tool_prefetch import prefetch_tools
from fdai.agents._framework.tool_semantic import SemanticToolPlanner
from fdai.agents.bragi import Bragi, RoutingDecision, Turn


class RuntimeConversationPort:
    """Mixin implementing PantheonRuntime's read-only conversational facade."""

    _bragi: Bragi | None
    _conversation_tools: AgentConversationToolRegistry | None
    _semantic_tool_planner: SemanticToolPlanner | None

    async def ask(
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        locale: str = "en",
        initiator_role: str | None = None,
        allow_action_proposal: bool = False,
        materialize_handoff: bool = False,
    ) -> Turn | None:
        """Operator conversational-port entry point.

        Routes a natural-language question through Bragi to the right
        primary agent, tracking a per-user session (Bragi enforces the
        no-cross-user invariant). Returns ``None`` when Bragi is disabled
        (the conversational port is off). Distinct from the typed
        pub/sub port: a conversational request that wants an action must
        re-enter the typed pipeline, never bypass it.
        """
        if self._bragi is None:
            return None
        return await self._bragi.ask(
            session_id=session_id,
            user_id=user_id,
            question=question,
            locale=locale,
            initiator_role=initiator_role,
            allow_action_proposal=allow_action_proposal,
            materialize_handoff=materialize_handoff,
        )

    def route_conversation(
        self,
        judgment: SemanticJudgmentProposal,
    ) -> RoutingDecision | None:
        """Project one verified judgment without exposing agent instances."""
        if self._bragi is None:
            return None
        return self._bragi.route(judgment)

    def should_delegate_conversation(
        self,
        question: str,
        view_context: dict[str, Any],
    ) -> bool:
        """Return Bragi's current-screen versus agent-owned scope decision."""
        if self._bragi is None:
            return False
        return self._bragi.should_delegate(question, view_context)

    async def contribute_conversation(
        self,
        agent_name: str,
        question: str,
        *,
        requester: str = "Bragi",
    ) -> dict[str, Any] | None:
        """Collect one read-only contribution through Bragi's A2A boundary."""
        if self._bragi is None:
            return None
        return await self._bragi.introspect_agent(
            agent_name,
            question,
            requester=requester,
            context={"answer_planning": "shadow", "nested_round": False},
        )

    async def introspect(
        self,
        agent_name: str,
        question: str,
        *,
        requester: str,
        correlation_id: str = "",
    ) -> dict[str, Any] | None:
        """Route one read-only agent-to-agent question through Bragi."""
        if self._bragi is None:
            return None
        return await self._bragi.introspect_agent(
            agent_name,
            question,
            requester=requester,
            context={"correlation_id": correlation_id} if correlation_id else None,
        )

    async def deliberate(
        self,
        *,
        question: str,
        requester: str,
        correlation_id: str = "",
        locale: str = "en",
        reuse_semantic_route: bool = True,
        fixed_assurance_facts: Mapping[str, Mapping[str, object]] | None = None,
        fixed_assurance_scenario_id: str | None = None,
    ) -> dict[str, Any]:
        """Run bounded read-only T1/T2 discussion through Bragi."""
        if self._bragi is None:
            return {
                "status": "abstain",
                "reason": "conversational_port_unavailable",
                "authority": "presentation_only",
                "rounds": [],
                "trace_ref": correlation_id,
            }
        return await self._bragi.deliberate(
            question=question,
            requester=requester,
            correlation_id=correlation_id,
            locale=locale,
            reuse_semantic_route=reuse_semantic_route,
            fixed_assurance_facts=fixed_assurance_facts,
            fixed_assurance_scenario_id=fixed_assurance_scenario_id,
        )

    def plan_conversation_tools(
        self,
        requested_tool_ids: Sequence[str],
        *,
        agents: Sequence[str] = (),
        limit: int = MAX_TOOL_PLANS,
    ) -> tuple[ConversationToolPlan, ...]:
        """Validate exact model-selected owned read tool ids."""
        return plan_conversation_tools(requested_tool_ids, agents=agents, limit=limit)

    async def prefetch_conversation_tools(
        self,
        question: str,
        *,
        agents: Sequence[str] = (),
        limit: int = MAX_TOOL_PLANS,
        trace_ref: str = "",
    ) -> tuple[AgentToolResult, ...]:
        """Run the tools this question asks for and return their results."""
        registry = self._conversation_tools
        if registry is None:
            return ()
        return await prefetch_tools(
            question,
            registry=registry,
            semantic=self._semantic_tool_planner,
            agents=agents,
            limit=limit,
            trace_ref=trace_ref,
        )

    async def invoke_conversation_tool(
        self,
        *,
        agent_name: str,
        tool_id: str,
        question: str,
        trace_ref: str = "",
    ) -> AgentToolResult:
        """Invoke one exact-owner read tool through the agent's guarded port."""
        registry = self._conversation_tools
        if registry is None:
            raise RuntimeError("agent conversation tool registry is unavailable")
        return await registry.invoke(
            agent_name=agent_name,
            tool_id=tool_id,
            question=question,
            trace_ref=trace_ref,
        )


__all__ = ["RuntimeConversationPort"]
