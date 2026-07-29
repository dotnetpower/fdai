"""Parallel read-evidence pipeline for operator-chat transports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

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
    PlannedChatToolResolver,
    _is_explicit_tool_command,
    _screen_incident_context,
    _selected_agent,
    _with_agent_evidence,
    _with_operational_evidence,
    _with_tool_evidence,
    _with_web_evidence,
    merge_evidence_branch_results,
)
from fdai.delivery.read_api.routes.chat_inventory import needs_inventory_evidence
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
    planned_tool_resolver: PlannedChatToolResolver | None = None,
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
        "_agent_session_target",
        "_web_evidence",
    ):
        base_context.pop(key, None)
    specs: list[EvidenceBranchSpec] = []
    semantic_plan = base_context.get("_turn_plan")
    has_semantic_plan = isinstance(semantic_plan, Mapping)
    planned_tool_name = (
        semantic_plan.get("tool_name") if isinstance(semantic_plan, Mapping) else None
    )
    planned_arguments = (
        semantic_plan.get("arguments") if isinstance(semantic_plan, Mapping) else None
    )
    planned_read = (
        isinstance(semantic_plan, Mapping)
        and semantic_plan.get("kind") == "read_tool"
        and isinstance(planned_tool_name, str)
        and isinstance(planned_arguments, Mapping)
    )
    planned_agent = (
        planned_tool_name.removeprefix("agent:")
        if isinstance(planned_tool_name, str) and planned_tool_name.startswith("agent:")
        else None
    )
    planned_web = planned_tool_name == "web_search"
    planned_direct_read = planned_read and planned_agent is None and not planned_web
    search_intent = classify_search_intent(prompt)
    web_requested = planned_web if has_semantic_plan else search_intent.route == "web"
    read_investigation = (
        classify_read_investigation_intent(prompt) is not None
        and resource_name_from_question(prompt) is not None
    )
    explicit_web_search = search_intent.reason in {
        "explicit_web_search",
        "explicit_web_context",
        "explicit_search_request",
    }
    deterministic_inventory_turn = (
        needs_inventory_evidence(prompt) and not explicit_web_search and not read_investigation
    )
    selected_incident_turn = _screen_incident_context(
        prompt, base_context
    ) is not None and not _is_explicit_tool_command(prompt)
    selected_agent = _selected_agent(prompt, conversation_context, target_agent)
    parallel_agent = not deterministic_inventory_turn and (
        planned_agent is not None
        or selected_agent is not None
        or (not has_semantic_plan and read_investigation)
    )
    parallel_web = (
        web_search_resolver is not None
        and not deterministic_inventory_turn
        and web_requested
        and "_behavior_evidence" not in base_context
        and "_screen_scope" not in base_context
    )

    if (
        planned_direct_read
        and planned_tool_resolver is not None
        and not selected_incident_turn
        and not deterministic_inventory_turn
    ):
        selected_tool_name = cast(str, planned_tool_name)
        selected_arguments = cast(Mapping[str, object], planned_arguments)

        async def resolve_planned_tool(_observe: BranchProgressObserver) -> dict[str, Any]:
            resolved = await planned_tool_resolver.resolve_planned(
                selected_tool_name,
                selected_arguments,
                principal_id=user_id,
            )
            enriched = dict(base_context)
            if resolved is not None:
                enriched["_tool_evidence"] = dict(resolved)
            return enriched

        specs.append(
            EvidenceBranchSpec(
                EvidenceBranchKind.TOOL,
                resolve_planned_tool,
                ("_tool_evidence",),
            )
        )
    elif (
        (not has_semantic_plan or deterministic_inventory_turn)
        and tool_resolver is not None
        and not selected_incident_turn
    ):

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

    if (not has_semantic_plan or selected_incident_turn) and evidence_resolver is not None:

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
            target_agent=planned_agent or target_agent,
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
            if planned_web and isinstance(planned_arguments, Mapping):
                resolved = await web_search_resolver.resolve_planned(
                    {str(key): value for key, value in planned_arguments.items()},
                    base_context,
                    progress_observer=observe,
                )
                enriched = dict(base_context)
                if resolved is not None:
                    enriched["_web_evidence"] = dict(resolved)
                return enriched
            return await _with_web_evidence(
                prompt,
                dict(base_context),
                web_search_resolver,
                progress_observer=observe,
                allow_agent_request=selected_agent is not None,
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
        allow_agent_web=web_requested,
    )

    if not parallel_agent and not selected_incident_turn and not deterministic_inventory_turn:

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
            allow_agent_web=web_requested,
        )

    if (
        not parallel_web
        and web_search_resolver is not None
        and not selected_incident_turn
        and not deterministic_inventory_turn
        and selected_agent is None
    ):

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
            allow_agent_web=web_requested,
        )
    if target_agent is not None and selected_agent is not None:
        merged["_agent_session_target"] = selected_agent
    return merged


__all__ = ["resolve_parallel_chat_evidence"]
