"""Parallel read-evidence pipeline for operator-chat transports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.read_investigation.routing import (
    classify_read_investigation_intent,
    resource_name_from_question,
)
from fdai.delivery.read_api.routes.chat_evidence_branches import (
    BranchProgressObserver,
    EvidenceBranchKind,
    EvidenceBranchSpec,
    resolve_evidence_branches,
)
from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
    AgentChatDelegate,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    _selected_agent,
    _with_agent_evidence,
    _with_operational_evidence,
    _with_tool_evidence,
    _with_web_evidence,
    merge_evidence_branch_results,
)
from fdai.delivery.read_api.routes.chat_web_search_intent import classify_search_intent


async def resolve_parallel_chat_evidence(
    *,
    request_id: str,
    prompt: str,
    view_context: Mapping[str, Any],
    user_id: str,
    session_id: str,
    conversation_context: Mapping[str, str] | None,
    target_agent: str | None,
    tool_resolver: ChatToolResolver | None,
    evidence_resolver: OperationalEvidenceResolverProtocol | None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None,
    progress_observer: BranchProgressObserver,
) -> dict[str, Any]:
    """Resolve independent evidence snapshots and merge established authority order."""

    base_context = dict(view_context)
    for key in (
        "_tool_evidence",
        "_current_screen_tool",
        "_operational_evidence",
        "_agent_evidence",
        "_web_evidence",
    ):
        base_context.pop(key, None)
    specs: list[EvidenceBranchSpec] = []
    parallel_agent = _selected_agent(prompt, conversation_context, target_agent) is not None or (
        classify_read_investigation_intent(prompt) is not None
        and resource_name_from_question(prompt) is not None
    )
    parallel_web = (
        web_search_resolver is not None
        and classify_search_intent(prompt).route == "web"
        and not parallel_agent
        and "_behavior_evidence" not in base_context
        and "_screen_scope" not in base_context
    )

    if tool_resolver is not None:

        async def resolve_tool(observe: BranchProgressObserver) -> dict[str, Any]:
            return await _with_tool_evidence(
                prompt,
                dict(base_context),
                tool_resolver,
                principal_id=user_id,
                progress_observer=observe,
            )

        specs.append(
            EvidenceBranchSpec(
                EvidenceBranchKind.TOOL,
                resolve_tool,
                ("_tool_evidence", "_current_screen_tool"),
            )
        )

    if evidence_resolver is not None:

        async def resolve_operational(observe: BranchProgressObserver) -> dict[str, Any]:
            del observe
            return await _with_operational_evidence(
                prompt,
                dict(base_context),
                evidence_resolver,
                conversation_context=conversation_context,
            )

        specs.append(
            EvidenceBranchSpec(
                EvidenceBranchKind.OPERATIONAL,
                resolve_operational,
                ("_operational_evidence",),
            )
        )

    async def resolve_agent(observe: BranchProgressObserver) -> dict[str, Any]:
        return await _with_agent_evidence(
            prompt,
            dict(base_context),
            agent_delegate,
            user_id=user_id,
            session_id=session_id,
            conversation_context=conversation_context,
            target_agent=target_agent,
            progress_observer=observe,
        )

    if parallel_agent:
        specs.append(
            EvidenceBranchSpec(
                EvidenceBranchKind.AGENT,
                resolve_agent,
                ("_agent_evidence",),
            )
        )

    if parallel_web and web_search_resolver is not None:

        async def resolve_web(observe: BranchProgressObserver) -> dict[str, Any]:
            return await _with_web_evidence(
                prompt,
                dict(base_context),
                web_search_resolver,
                progress_observer=observe,
            )

        specs.append(
            EvidenceBranchSpec(
                EvidenceBranchKind.PUBLIC_WEB,
                resolve_web,
                ("_web_evidence",),
            )
        )

    results = (
        await resolve_evidence_branches(
            request_id=request_id,
            base_context=base_context,
            specs=specs,
            progress_observer=progress_observer,
        )
        if specs
        else ()
    )
    merged = merge_evidence_branch_results(
        prompt,
        base_context,
        results,
        conversation_context=conversation_context,
        target_agent=target_agent,
    )

    if not parallel_agent:

        async def resolve_dependent_agent(observe: BranchProgressObserver) -> dict[str, Any]:
            return await _with_agent_evidence(
                prompt,
                dict(merged),
                agent_delegate,
                user_id=user_id,
                session_id=session_id,
                conversation_context=conversation_context,
                target_agent=target_agent,
                progress_observer=observe,
            )

        agent_results = await resolve_evidence_branches(
            request_id=request_id,
            base_context=merged,
            specs=(
                EvidenceBranchSpec(
                    EvidenceBranchKind.AGENT,
                    resolve_dependent_agent,
                    ("_agent_evidence",),
                ),
            ),
            progress_observer=progress_observer,
        )
        merged = merge_evidence_branch_results(
            prompt,
            merged,
            agent_results,
            conversation_context=conversation_context,
            target_agent=target_agent,
        )

    if not parallel_web and web_search_resolver is not None:

        async def resolve_dependent_web(observe: BranchProgressObserver) -> dict[str, Any]:
            return await _with_web_evidence(
                prompt,
                dict(merged),
                web_search_resolver,
                progress_observer=observe,
            )

        web_results = await resolve_evidence_branches(
            request_id=request_id,
            base_context=merged,
            specs=(
                EvidenceBranchSpec(
                    EvidenceBranchKind.PUBLIC_WEB,
                    resolve_dependent_web,
                    ("_web_evidence",),
                ),
            ),
            progress_observer=progress_observer,
        )
        merged = merge_evidence_branch_results(
            prompt,
            merged,
            web_results,
            conversation_context=conversation_context,
            target_agent=target_agent,
        )
    return merged


__all__ = ["resolve_parallel_chat_evidence"]
