"""Build one primary agent answer from its completed read tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.conversation_tools import (
    AgentConversationToolRegistry,
    AgentToolResult,
    AgentToolStatus,
)
from fdai.agents._framework.tool_planner import MAX_TOOL_PLANS, ConversationToolPlan
from fdai.agents._framework.tool_prefetch import gather_tools
from fdai.agents._framework.tool_semantic import SemanticToolPlanner


async def answer_from_owned_tools(
    *,
    agent_name: str,
    question: str,
    trace_ref: str,
    registry: AgentConversationToolRegistry,
    semantic: SemanticToolPlanner | None,
) -> dict[str, Any] | None:
    """Return a tool-grounded responder envelope, or ``None`` when no tool matched."""

    gathered = await gather_tools(
        question,
        registry=registry,
        semantic=semantic,
        agents=(agent_name,),
        limit=MAX_TOOL_PLANS,
        trace_ref=trace_ref,
        execute_limit=1,
        require_unique_top=True,
    )
    if not gathered.plans or gathered.ambiguous:
        return None
    selected_plan = gathered.plans[0]
    completed = len(gathered.results) == 1
    successful = all(result.status is AgentToolStatus.OK for result in gathered.results)
    if gathered.timed_out or not completed or not successful:
        first = gathered.results[0] if gathered.results else None
        return _envelope(
            agent_name=agent_name,
            answer=None,
            facts={"evidence_refs": []},
            trace_ref=trace_ref,
            results=gathered.results,
            policy_source=first,
            plan=selected_plan,
            fallback_reason=(
                "gather_timeout" if gathered.timed_out else "tool_evidence_incomplete"
            ),
            abstain_reason="tool_evidence_incomplete",
        )
    return _successful_envelope(
        agent_name,
        gathered.results,
        trace_ref=trace_ref,
        plan=selected_plan,
    )


def _successful_envelope(
    agent_name: str,
    results: tuple[AgentToolResult, ...],
    *,
    trace_ref: str,
    plan: ConversationToolPlan,
) -> dict[str, Any]:
    evidence_refs = list(dict.fromkeys(ref for result in results for ref in result.evidence_refs))
    if len(results) == 1:
        facts = dict(results[0].facts)
        facts["evidence_refs"] = evidence_refs
    else:
        facts = {
            "tool_results": [
                {"tool_id": result.tool_id, "facts": dict(result.facts)} for result in results
            ],
            "evidence_refs": evidence_refs,
        }
    answer = "\n".join(result.answer for result in results if result.answer is not None)
    return _envelope(
        agent_name=agent_name,
        answer=answer,
        facts=facts,
        trace_ref=trace_ref,
        results=results,
        policy_source=results[0],
        plan=plan,
        fallback_reason=None,
        abstain_reason=None,
    )


def _envelope(
    *,
    agent_name: str,
    answer: str | None,
    facts: Mapping[str, Any],
    trace_ref: str,
    results: tuple[AgentToolResult, ...],
    policy_source: AgentToolResult | None,
    plan: ConversationToolPlan,
    fallback_reason: str | None,
    abstain_reason: str | None,
) -> dict[str, Any]:
    policy = (
        {
            "version": policy_source.charter_version,
            "charter_sha256": policy_source.charter_sha256,
            "prompt_sha256": policy_source.prompt_sha256,
            "tools": list(policy_source.allowed_tools),
        }
        if policy_source is not None
        else {}
    )
    return {
        "primary_agent": agent_name,
        "answer": answer,
        "facts": dict(facts),
        "trace_ref": trace_ref,
        "abstain_reason": abstain_reason,
        "conversation_policy": policy,
        "conversation_tools": [result.tool_id for result in results],
        "conversation_tool_plan": {
            "agent": plan.agent,
            "tool_id": plan.tool_id,
            "tier": plan.tier,
            "score": plan.score,
        },
        "conversation_tool_results": (
            [
                {
                    "tool_id": result.tool_id,
                    "status": result.status.value,
                    "reason": result.reason,
                    "evidence_ref_count": result.evidence_ref_count,
                    "evidence_refs_truncated": result.evidence_refs_truncated,
                }
                for result in results
            ]
            if results
            else [
                {
                    "tool_id": plan.tool_id,
                    "status": AgentToolStatus.ABSTAIN.value,
                    "reason": fallback_reason,
                    "evidence_ref_count": 0,
                    "evidence_refs_truncated": False,
                }
            ]
        ),
    }


__all__ = ["answer_from_owned_tools"]
