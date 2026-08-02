"""Execute validated conversation intent graphs through read-only provider seams."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

from fdai.delivery.operator_api.routes.chat_evidence_branches import BranchProgressObserver
from fdai.delivery.operator_api.routes.chat_evidence_enrichment import (
    AgentChatDelegate,
    ChatWebSearchEvidenceResolver,
    PlannedChatToolResolver,
)
from fdai.delivery.operator_api.routes.chat_intent_graph import (
    EvidenceMode,
    IntentGoal,
    IntentGraph,
)

_MAX_CONCURRENCY: Final = 4
_GOAL_TIMEOUT_SECONDS: Final = 20.0


async def resolve_intent_graph_evidence(
    *,
    request_id: str,
    prompt: str,
    graph: IntentGraph,
    view_context: Mapping[str, Any],
    user_id: str,
    session_id: str,
    planned_tool_resolver: PlannedChatToolResolver | None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None,
    progress_observer: BranchProgressObserver,
) -> dict[str, Any]:
    """Resolve graph goals by dependency wave and retain every terminal receipt."""
    merged = dict(view_context)
    pending = {goal.goal_id: goal for goal in graph.goals}
    completed: set[str] = set()
    receipts: list[dict[str, Any]] = []
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    while pending:
        ready = [
            goal
            for goal in graph.goals
            if goal.goal_id in pending and set(goal.depends_on).issubset(completed)
        ]
        if not ready:
            raise RuntimeError("validated intent graph has no executable dependency wave")

        async def resolve(goal: IntentGoal) -> tuple[IntentGoal, dict[str, Any]]:
            async with semaphore:
                receipt = await _resolve_goal(
                    request_id=request_id,
                    prompt=prompt,
                    goal=goal,
                    base_context=merged,
                    user_id=user_id,
                    session_id=session_id,
                    planned_tool_resolver=planned_tool_resolver,
                    agent_delegate=agent_delegate,
                    web_search_resolver=web_search_resolver,
                    progress_observer=progress_observer,
                )
                return goal, receipt

        wave = await asyncio.gather(*(resolve(goal) for goal in ready))
        for goal, receipt in wave:
            receipts.append(receipt)
            _merge_compatibility_evidence(merged, receipt)
            completed.add(goal.goal_id)
            pending.pop(goal.goal_id)
    aggregate_status = _aggregate_status(receipts)
    merged["_intent_graph_evidence"] = {
        "schema_version": 1,
        "status": aggregate_status,
        "evidence_mode": _evidence_mode(receipts, aggregate_status),
        "goals": receipts,
    }
    return merged


async def _resolve_goal(
    *,
    request_id: str,
    prompt: str,
    goal: IntentGoal,
    base_context: Mapping[str, Any],
    user_id: str,
    session_id: str,
    planned_tool_resolver: PlannedChatToolResolver | None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None,
    progress_observer: BranchProgressObserver,
) -> dict[str, Any]:
    branch_id = f"{request_id}:{goal.goal_id}"
    started = time.monotonic()
    await progress_observer(_progress(branch_id, goal, "running", "Resolving intent goal", 0))
    status = "completed"
    reason: str | None = None
    evidence: Mapping[str, Any] | None = None
    try:
        async with asyncio.timeout(_GOAL_TIMEOUT_SECONDS):
            evidence = await _dispatch_goal(
                prompt=prompt,
                goal=goal,
                base_context=base_context,
                user_id=user_id,
                session_id=session_id,
                planned_tool_resolver=planned_tool_resolver,
                agent_delegate=agent_delegate,
                web_search_resolver=web_search_resolver,
                progress_observer=progress_observer,
            )
        if goal.capability is not None and evidence is None:
            status = "unavailable"
            reason = "capability_unavailable"
    except TimeoutError:
        status = "timed_out"
        reason = "capability_timeout"
    except asyncio.CancelledError:
        await progress_observer(_progress(branch_id, goal, "cancelled", "Intent goal cancelled", 0))
        raise
    except ValueError:
        status = "unavailable"
        reason = "capability_rejected"
    except Exception:  # noqa: BLE001 - isolate one read-only goal
        status = "failed"
        reason = "capability_failed"
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    receipt: dict[str, Any] = {
        "goal_id": goal.goal_id,
        "intent": goal.intent.value,
        "capability": goal.capability,
        "evidence_mode": goal.evidence_mode.value,
        "status": status,
        "duration_ms": duration_ms,
        "depends_on": list(goal.depends_on),
    }
    if reason is not None:
        receipt["reason"] = reason
    if evidence is not None:
        receipt["evidence"] = dict(evidence)
    await progress_observer(
        _progress(branch_id, goal, status, f"Intent goal {status}", duration_ms)
    )
    return receipt


async def _dispatch_goal(
    *,
    prompt: str,
    goal: IntentGoal,
    base_context: Mapping[str, Any],
    user_id: str,
    session_id: str,
    planned_tool_resolver: PlannedChatToolResolver | None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None,
    progress_observer: BranchProgressObserver,
) -> Mapping[str, Any] | None:
    capability = goal.capability
    if capability is None:
        return {
            "authority": "model_knowledge"
            if goal.evidence_mode is EvidenceMode.MODEL_KNOWLEDGE
            else "screen",
            "freshness_required": goal.freshness_required,
        }
    if capability == "web_search":
        if web_search_resolver is None:
            return None
        return await web_search_resolver.resolve_planned(
            goal.arguments,
            base_context,
            progress_observer=progress_observer,
        )
    if capability.startswith("agent:"):
        if agent_delegate is None:
            return None
        agent = capability.removeprefix("agent:")
        delegated_prompt = f"@{agent} {prompt}"
        progressive = getattr(agent_delegate, "delegate_with_progress", None)
        if callable(progressive):
            progressive_result = await progressive(
                prompt=delegated_prompt,
                user_id=user_id,
                session_id=session_id,
                progress_observer=progress_observer,
            )
            return dict(progressive_result) if isinstance(progressive_result, Mapping) else None
        return await agent_delegate.delegate(
            prompt=delegated_prompt,
            user_id=user_id,
            session_id=session_id,
        )
    if planned_tool_resolver is None:
        return None
    return await planned_tool_resolver.resolve_planned(
        capability,
        goal.arguments,
        principal_id=user_id,
    )


def _merge_compatibility_evidence(context: dict[str, Any], receipt: Mapping[str, Any]) -> None:
    evidence = receipt.get("evidence")
    if not isinstance(evidence, Mapping):
        return
    capability = receipt.get("capability")
    if capability == "web_search":
        context["_web_evidence"] = dict(evidence)
    elif isinstance(capability, str) and capability.startswith("agent:"):
        context["_agent_evidence"] = dict(evidence)
    elif isinstance(capability, str):
        context["_tool_evidence"] = dict(evidence)


def _aggregate_status(receipts: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(receipt.get("status")) for receipt in receipts}
    if statuses == {"completed"}:
        return "completed"
    if "completed" in statuses:
        return "partial"
    if "failed" in statuses or "timed_out" in statuses:
        return "failed"
    return "unavailable"


def _evidence_mode(receipts: Sequence[Mapping[str, Any]], status: str) -> str:
    if status == "partial":
        return "partial"
    completed_modes = {
        str(receipt.get("evidence_mode"))
        for receipt in receipts
        if receipt.get("status") == "completed"
    }
    if not completed_modes:
        return "held_for_review"
    if completed_modes == {"model_knowledge"}:
        return "model_knowledge"
    if completed_modes == {"web"}:
        return "web_grounded"
    if completed_modes == {"screen"}:
        return "screen_grounded"
    if completed_modes == {"operational"}:
        return "operational_grounded"
    return "mixed_grounded"


def _progress(
    branch_id: str,
    goal: IntentGoal,
    status: str,
    summary: str,
    duration_ms: int,
) -> dict[str, Any]:
    kind = (
        "public_web"
        if goal.capability == "web_search"
        else "agent"
        if isinstance(goal.capability, str) and goal.capability.startswith("agent:")
        else "tool"
    )
    return {
        "event": "branch",
        "branch_id": branch_id,
        "branch_kind": kind,
        "parent_branch_id": None,
        "status": status,
        "summary": summary,
        "duration_ms": duration_ms,
        "evidence_refs": [],
    }


__all__ = ["resolve_intent_graph_evidence"]
