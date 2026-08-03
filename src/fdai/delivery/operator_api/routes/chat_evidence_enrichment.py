"""Server-owned evidence enrichment and response provenance helpers."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from inspect import Parameter, signature
from typing import Any, Protocol

from fdai.agents import PANTHEON_NAMES
from fdai.core.conversation.narrator import default_tool_schemas
from fdai.core.read_investigation import (
    classify_read_investigation_intent,
    resource_name_from_question,
)
from fdai.delivery.agent_introspection_bus import addressed_agent
from fdai.delivery.operator_api.routes.chat_action_context import needs_action_context
from fdai.delivery.operator_api.routes.chat_conversation_context import (
    needs_conversation_context,
)
from fdai.delivery.operator_api.routes.chat_data_sources import needs_read_source_evidence
from fdai.delivery.operator_api.routes.chat_evidence import needs_operational_evidence
from fdai.delivery.operator_api.routes.chat_evidence_branches import (
    EvidenceBranchKind,
    EvidenceBranchResult,
    EvidenceBranchStatus,
)
from fdai.delivery.operator_api.routes.chat_execution_output import inventory_execution_output
from fdai.delivery.operator_api.routes.chat_inventory import (
    inventory_execution_query,
    inventory_screen_scope_unavailable_evidence,
    needs_inventory_evidence,
)
from fdai.delivery.operator_api.routes.chat_log_query import needs_log_query
from fdai.delivery.operator_api.routes.chat_preincident_activity import parse_preincident_activity
from fdai.delivery.operator_api.routes.chat_prompt import (
    _AGENT_NAME_TOKEN,
    _CONCEPT_DOMAIN,
    _is_concept_query,
)
from fdai.delivery.operator_api.routes.chat_subscription_health import needs_subscription_health
from fdai.delivery.operator_api.routes.chat_t2_recovery import needs_t2_recovery_evidence
from fdai.delivery.operator_api.routes.inventory_provider_execution import (
    project_inventory_provider_execution,
)


class OperationalEvidenceResolverProtocol(Protocol):
    """Read-only server evidence seam used only for cross-screen questions."""

    async def resolve(
        self,
        prompt: str,
        *,
        conversation_context: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any] | None: ...


class ChatBehaviorEvidenceResolver(Protocol):
    """Server-owned structured system-behavior evidence resolver."""

    async def resolve(self, prompt: str) -> Mapping[str, Any] | None: ...


class AgentChatDelegate(Protocol):
    """Read-only server-side delegation to Bragi and the pantheon."""

    async def delegate(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
    ) -> Mapping[str, Any] | None: ...


AgentProgressObserver = Callable[[Mapping[str, Any]], Awaitable[None]]


class ChatToolResolver(Protocol):
    """Read-only deterministic tool resolver for direct operator intents."""

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> Mapping[str, Any] | None: ...


class PlannedChatToolResolver(Protocol):
    """Execute one server-validated read plan without natural-language matching."""

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> Mapping[str, Any] | None: ...


class ChatWebSearchEvidenceResolver(Protocol):
    """Read-only public-web evidence resolver for explicitly eligible turns."""

    async def resolve(
        self,
        prompt: str,
        view_context: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...

    async def resolve_planned(
        self,
        arguments: Mapping[str, object],
        view_context: Mapping[str, Any],
        *,
        progress_observer: AgentProgressObserver | None = None,
    ) -> Mapping[str, Any] | None: ...


_VIEW_EXPLANATION_INTENT = re.compile(
    r"\b(connect(?:ed|s|ion)?|relationship|relate[ds]?|create[ds]?|creation|criteri(?:a|on)|"
    r"owner|ownership|dedup(?:e|lication)?|repeat|close[ds]?|closure|provenance|source|why)\b"
    "|연결|관계|생성|기준|소유|담당|중복|반복|종료|닫|출처|근거|왜",
    re.IGNORECASE,
)
_SELECTED_INCIDENT_REFERENCE = re.compile(
    r"\b(?:this|that|selected)\s+(?:incident|one)\b|\bwhat about (?:this|it)\b"
    r"|이\s*인시던트|선택한\s*인시던트|이거|이건|이게|얘는",
    re.IGNORECASE,
)
_EXPLICIT_INVENTORY_READ = re.compile(
    r"\b(?:show|list|display|find|query)\b.{0,48}\b(?:inventory|resources?)\b|"
    r"\b(?:inventory|resources?)\b.{0,48}\b(?:show|list|display|find|query)\b|"
    r"(?:인벤토리|inventory|리소스).{0,32}(?:보여|목록|조회)|"
    r"(?:보여|목록|조회).{0,32}(?:인벤토리|inventory|리소스)",
    re.IGNORECASE,
)
_EXPLICIT_TOOL_VERBS = frozenset(schema.verb for schema in default_tool_schemas())


def _uses_view_explanations(prompt: str, view_context: Mapping[str, Any]) -> bool:
    return isinstance(view_context.get("explanations"), Mapping) and bool(
        _VIEW_EXPLANATION_INTENT.search(prompt)
    )


def _supports_conversation_context(resolver: OperationalEvidenceResolverProtocol) -> bool:
    try:
        parameters = signature(resolver.resolve).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.name == "conversation_context" or parameter.kind is Parameter.VAR_KEYWORD
        for parameter in parameters
    )


async def _with_behavior_evidence(
    prompt: str,
    view_context: dict[str, Any],
    resolver: ChatBehaviorEvidenceResolver | None,
) -> dict[str, Any]:
    """Replace client-supplied behavior data with server-owned evidence."""

    enriched = dict(view_context)
    enriched.pop("_behavior_evidence", None)
    if resolver is None or "_screen_scope" in enriched:
        return enriched
    evidence = await resolver.resolve(prompt)
    if evidence is not None:
        enriched["_behavior_evidence"] = dict(evidence)
    return enriched


def _with_screen_scope(
    prompt: str,
    view_context: dict[str, Any],
    delegate: AgentChatDelegate | None,
    *,
    conversation_context: Mapping[str, str] | None = None,
    target_agent: str | None = None,
) -> dict[str, Any]:
    """Apply Bragi's screen-versus-agent authority decision before retrieval."""

    enriched = dict(view_context)
    enriched.pop("_screen_scope", None)
    selected_agent = target_agent or (
        conversation_context.get("selected_agent") if conversation_context is not None else None
    )
    if selected_agent in PANTHEON_NAMES or _explicit_agent_requested(prompt):
        return enriched
    if delegate is None:
        return enriched
    should_delegate = getattr(delegate, "should_delegate", None)
    if callable(should_delegate) and not should_delegate(prompt, enriched):
        enriched["_screen_scope"] = {
            "authority": "current_screen",
            "route_id": str(enriched.get("routeId") or ""),
        }
    return enriched


async def _with_operational_evidence(
    prompt: str,
    view_context: dict[str, Any],
    resolver: OperationalEvidenceResolverProtocol | None,
    *,
    conversation_context: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Replace any client-supplied evidence with server-owned evidence."""

    enriched = dict(view_context)
    enriched.pop("_operational_evidence", None)
    if str(enriched.get("routeId") or "").lower() == "audit":
        return enriched
    screen_context = _screen_incident_context(prompt, enriched)
    operational_question = (
        needs_operational_evidence(prompt, enriched) or screen_context is not None
    )
    effective_context = conversation_context or screen_context
    if (
        resolver is None
        or "_inventory_screen_scope" in enriched
        or "_screen_scope" in enriched
        or "_behavior_evidence" in enriched
        or (effective_context is None and not operational_question)
        or "_tool_evidence" in enriched
        or "_current_screen_tool" in enriched
    ):
        return enriched
    evidence = (
        await resolver.resolve(prompt, conversation_context=effective_context)
        if _supports_conversation_context(resolver)
        else await resolver.resolve(prompt)
    )
    if evidence is not None:
        enriched["_operational_evidence"] = dict(evidence)
    return enriched


def _screen_incident_context(
    prompt: str,
    view_context: Mapping[str, Any],
) -> dict[str, str] | None:
    """Return a bounded incident selection hint from an owning screen."""

    route = str(view_context.get("routeId") or "").lower()
    if route == "incidents":
        if _EXPLICIT_INVENTORY_READ.search(prompt):
            return None
        records = view_context.get("records")
        selected = records.get("selected_incident") if isinstance(records, Mapping) else None
        incident = selected[0] if isinstance(selected, list) and len(selected) == 1 else None
        if not isinstance(incident, Mapping):
            return None
        correlation_id = incident.get("correlation_id")
        incident_id = incident.get("incident_id") or incident.get("ticket_id")
        title = incident.get("title")
        references_selection = bool(
            _SELECTED_INCIDENT_REFERENCE.search(prompt)
            or (isinstance(correlation_id, str) and correlation_id.casefold() in prompt.casefold())
            or (isinstance(title, str) and title.casefold() in prompt.casefold())
        )
        if not references_selection:
            return None
        if not isinstance(correlation_id, str) or not 0 < len(correlation_id.strip()) <= 256:
            return None
        normalized_correlation = correlation_id.strip()
        if incident_id is None:
            normalized_incident = f"INC-{normalized_correlation}"
        elif isinstance(incident_id, str) and 0 < len(incident_id.strip()) <= 256:
            normalized_incident = incident_id.strip()
        else:
            return None
        return {
            "kind": "incident",
            "incident_id": normalized_incident,
            "correlation_id": normalized_correlation,
        }
    if route != "trace" or not needs_operational_evidence(prompt, view_context):
        return None
    facts = view_context.get("facts")
    if not isinstance(facts, list):
        return None
    correlation_id = next(
        (
            value
            for fact in facts
            if isinstance(fact, Mapping)
            and fact.get("key") == "correlation_id"
            and isinstance((value := fact.get("value")), str)
            and value.strip()
            and len(value) <= 256
        ),
        None,
    )
    if correlation_id is None:
        return None
    return {
        "kind": "incident",
        "incident_id": f"INC-{correlation_id}",
        "correlation_id": correlation_id,
    }


async def _with_agent_evidence(
    prompt: str,
    view_context: dict[str, Any],
    delegate: AgentChatDelegate | None,
    *,
    user_id: str,
    session_id: str,
    conversation_context: Mapping[str, str] | None = None,
    target_agent: str | None = None,
    progress_observer: AgentProgressObserver | None = None,
) -> dict[str, Any]:
    """Replace client-supplied delegation data with a server-owned result."""

    enriched = dict(view_context)
    enriched.pop("_agent_evidence", None)
    preincident_read = parse_preincident_activity(prompt) is not None
    if "_screen_scope" in enriched and not preincident_read:
        return enriched
    if preincident_read:
        enriched.pop("_screen_scope", None)
    current_screen_tool = enriched.pop("_current_screen_tool", None)
    selected_agent = _selected_agent(prompt, conversation_context, target_agent)
    agent_owned = selected_agent is not None
    explicit_agent = _explicit_agent_requested(prompt)
    read_investigation = preincident_read or (
        classify_read_investigation_intent(prompt) is not None
        and resource_name_from_question(prompt) is not None
    )
    if (
        ("_behavior_evidence" in enriched and not agent_owned and not preincident_read)
        or ("_operational_evidence" in enriched and not agent_owned)
        or ("_tool_evidence" in enriched and not read_investigation and not agent_owned)
        or (current_screen_tool is not None and not agent_owned)
        or _uses_view_explanations(prompt, enriched)
        or (_is_concept_query(prompt) and _CONCEPT_DOMAIN.search(prompt) and not explicit_agent)
    ):
        return enriched
    if delegate is None:
        if selected_agent is not None:
            enriched["_agent_evidence"] = _agent_handoff(
                selected_agent,
                reason="agent_conversational_port_unavailable",
            )
        return enriched
    routed_prompt = _selected_agent_prompt(prompt, conversation_context, target_agent)
    progressive = getattr(delegate, "delegate_with_progress", None)
    evidence = (
        await progressive(
            prompt=routed_prompt,
            user_id=user_id,
            session_id=session_id,
            progress_observer=progress_observer,
        )
        if progress_observer is not None and callable(progressive)
        else await delegate.delegate(
            prompt=routed_prompt,
            user_id=user_id,
            session_id=session_id,
        )
    )
    if evidence is not None:
        if read_investigation or agent_owned:
            enriched.pop("_tool_evidence", None)
        if preincident_read or agent_owned:
            enriched.pop("_behavior_evidence", None)
        enriched["_agent_evidence"] = dict(evidence)
    elif selected_agent is not None:
        enriched["_agent_evidence"] = _agent_handoff(
            selected_agent,
            reason="agent_abstained_without_evidence",
        )
    return enriched


def _explicit_agent_requested(prompt: str) -> bool:
    names = {name.lower() for name in PANTHEON_NAMES}
    return any(token.lower() in names for token in _AGENT_NAME_TOKEN.findall(prompt))


def _selected_agent_prompt(
    prompt: str,
    conversation_context: Mapping[str, str] | None,
    target_agent: str | None,
) -> str:
    selected_agent = _selected_agent(prompt, conversation_context, target_agent)
    if selected_agent is None or addressed_agent(prompt) is not None:
        return prompt
    return f"@{selected_agent} {prompt}"


def _selected_agent(
    prompt: str,
    conversation_context: Mapping[str, str] | None,
    target_agent: str | None,
) -> str | None:
    addressed = addressed_agent(prompt)
    if addressed is not None:
        return addressed
    selected_agent = target_agent or (
        conversation_context.get("selected_agent") if conversation_context is not None else None
    )
    if selected_agent in PANTHEON_NAMES:
        return selected_agent
    canonical = {name.casefold(): name for name in PANTHEON_NAMES}
    for token in _AGENT_NAME_TOKEN.findall(prompt):
        explicit = canonical.get(token.casefold())
        if explicit is not None:
            return explicit
    return None


def _agent_handoff(agent: str, *, reason: str) -> dict[str, Any]:
    return {
        "primary_agent": "Bragi",
        "answer": None,
        "facts": {},
        "contributors": [],
        "handoff_from": agent,
        "handoff_reason": reason,
    }


async def _with_tool_evidence(
    prompt: str,
    view_context: dict[str, Any],
    resolver: ChatToolResolver | None,
    *,
    principal_id: str,
    conversation_context: Mapping[str, str] | None = None,
    progress_observer: AgentProgressObserver | None = None,
) -> dict[str, Any]:
    """Replace client-supplied tool output with a server-owned result."""

    enriched = dict(view_context)
    verified_prior_context = enriched.pop("_verified_prior_context", None)
    enriched.pop("_tool_evidence", None)
    enriched.pop("_current_screen_tool", None)
    selector_hold = enriched.pop("_read_investigation_context_hold", None)
    if isinstance(selector_hold, Mapping):
        enriched["_tool_evidence"] = dict(selector_hold)
        return enriched
    scope_hold = inventory_screen_scope_unavailable_evidence(
        enriched.get("_inventory_screen_scope")
    )
    if scope_hold is not None:
        enriched["_tool_evidence"] = scope_hold
        return enriched
    explicit_command = _is_explicit_tool_command(prompt)
    inventory_question = needs_inventory_evidence(prompt)
    subscription_health_question = needs_subscription_health(prompt)
    log_question = needs_log_query(prompt)
    action_context_question = needs_action_context(prompt)
    conversation_context_question = needs_conversation_context(prompt)
    read_source_question = needs_read_source_evidence(prompt)
    t2_recovery_question = needs_t2_recovery_evidence(prompt)
    if (
        resolver is None
        or (
            "_screen_scope" in enriched
            and not explicit_command
            and not inventory_question
            and not subscription_health_question
            and not log_question
            and not action_context_question
            and not conversation_context_question
            and not read_source_question
            and not t2_recovery_question
        )
        or (
            not explicit_command
            and not inventory_question
            and not subscription_health_question
            and not log_question
            and not action_context_question
            and not conversation_context_question
            and not read_source_question
            and not t2_recovery_question
            and ("_behavior_evidence" in enriched or "_operational_evidence" in enriched)
        )
    ):
        return enriched
    started_at = datetime.now(UTC)
    started = time.monotonic()
    progressive = getattr(resolver, "resolve_with_progress", None)
    contextual = getattr(resolver, "resolve_with_context", None)
    contextual_input: Mapping[str, Any] | None = (
        conversation_context
        if conversation_context is not None and conversation_context.get("kind") == "action"
        else verified_prior_context
        if isinstance(verified_prior_context, Mapping)
        else None
    )
    if callable(contextual) and contextual_input is not None:
        evidence = await contextual(
            prompt,
            principal_id=principal_id,
            context=contextual_input,
        )
    elif progress_observer is not None and callable(progressive):
        evidence = await progressive(
            prompt,
            principal_id=principal_id,
            progress_observer=progress_observer,
        )
    else:
        evidence = await resolver.resolve(prompt, principal_id=principal_id)
    if evidence is not None and progress_observer is not None:
        execution_events = _tool_execution_progress_events(
            evidence,
            started_at=started_at,
            duration_ms=max(0, round((time.monotonic() - started) * 1_000)),
        )
        for execution_event in execution_events:
            await progress_observer(execution_event)
    if evidence is not None:
        if explicit_command or evidence.get("tool") in {
            "describe_read_sources",
            "get_current_time",
            "query_inventory",
            "query_subscription_health",
            "query_t2_recovery",
        }:
            enriched.pop("_behavior_evidence", None)
            enriched.pop("_operational_evidence", None)
        if _tool_matches_current_route(evidence, enriched):
            enriched["_current_screen_tool"] = evidence.get("tool")
        else:
            enriched["_tool_evidence"] = dict(evidence)
    return enriched


def _tool_execution_progress_event(
    evidence: Mapping[str, Any],
    *,
    started_at: datetime,
    duration_ms: int,
) -> dict[str, object] | None:
    tool = evidence.get("tool")
    queries = {
        "query_subscription_health": {
            "operation": "query_subscription_health",
            "scope": "server-owned",
        },
        "query_t2_recovery": {
            "operation": "query_t2_recovery",
            "scope": "server-owned",
        },
    }
    labels = {
        "query_inventory": "Applied inventory query",
        "query_subscription_health": "Checked subscription health",
        "query_t2_recovery": "Read T2 recovery state",
    }
    if not isinstance(tool, str) or (tool not in queries and tool != "query_inventory"):
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    result_status = str(result.get("status") or "unavailable")
    completed = result_status in {"matched", "partial", "none", "ambiguous"}
    summary: dict[str, object] = {"status": result_status}
    for key in (
        "matched_count",
        "total_resources",
        "resource_count",
        "metric_checked",
        "metric_unavailable",
    ):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            summary[key] = value
    output, output_truncated = (
        inventory_execution_output(result)
        if tool == "query_inventory"
        else (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), False)
    )
    completed_at = datetime.now(UTC)
    execution: dict[str, object] = {
        "tool": "FDAI IQL" if tool == "query_inventory" else "FDAI server read",
        "command": (
            inventory_execution_query(evidence)
            if tool == "query_inventory"
            else json.dumps(queries[tool], indent=2, sort_keys=True)
        ),
        "input_kind": "query",
        "redacted": True,
        "output": output,
        "exit_code": None,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_ms": duration_ms,
    }
    if output_truncated:
        execution["output_truncated"] = True
    event: dict[str, object] = {
        "event": "activity",
        "activity_id": f"{tool}-execution",
        "kind": "read.execution",
        "status": "completed" if completed else "unavailable",
        "label": labels[tool],
        "detail": _tool_execution_detail(summary),
        "completed": 1 if completed else 0,
        "total": 1,
        "authority": str(evidence.get("authority") or "server_read_model"),
        "observed_at": completed_at.isoformat(),
        "execution": execution,
    }
    return event


def _tool_execution_progress_events(
    evidence: Mapping[str, Any],
    *,
    started_at: datetime,
    duration_ms: int,
) -> tuple[dict[str, object], ...]:
    primary = _tool_execution_progress_event(
        evidence,
        started_at=started_at,
        duration_ms=duration_ms,
    )
    if primary is None:
        return ()
    if evidence.get("tool") != "query_inventory":
        return (primary,)
    return (primary, *_inventory_provider_progress_events(evidence))


def _inventory_provider_progress_events(
    evidence: Mapping[str, Any],
) -> tuple[dict[str, object], ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    provider = project_inventory_provider_execution(result.get("provider_execution"))
    if provider is None:
        return ()
    snapshot_at = str(result.get("snapshot_at") or "snapshot time unavailable")
    backend = str(provider["backend"])
    subscription_id = provider.get("subscription_id")
    events: list[dict[str, object]] = []
    for index, command in enumerate(provider["commands"]):
        label = str(command["label"])
        is_arg = label == "resources" and backend == "azure_resource_graph"
        events.append(
            {
                "event": "activity",
                "activity_id": f"query_inventory-provider-{index}",
                "kind": "read.provider",
                "status": "completed",
                "label": (
                    "Listed Azure resource groups"
                    if label == "resource_groups"
                    else "Queried Azure Resource Graph"
                    if is_arg
                    else "Listed Azure resources"
                ),
                "detail": (
                    f"Subscription {subscription_id} - snapshot source observed at {snapshot_at}"
                    if isinstance(subscription_id, str)
                    else f"Snapshot source observed at {snapshot_at}"
                ),
                "completed": 1,
                "total": 1,
                "authority": backend,
                "observed_at": snapshot_at,
                "execution": {
                    "tool": "Azure Resource Graph via Azure CLI" if is_arg else "Azure CLI",
                    "command": str(command["command"]),
                    "input_kind": "command",
                    "redacted": True,
                    **(
                        {"duration_ms": command["duration_ms"]}
                        if isinstance(command.get("duration_ms"), int)
                        else {}
                    ),
                    **(
                        {
                            "output": json.dumps(command["result"], ensure_ascii=False, indent=2),
                            **(
                                {"output_truncated": True}
                                if command["result"].get("truncated") is True
                                else {}
                            ),
                        }
                        if isinstance(command.get("result"), Mapping)
                        else {}
                    ),
                },
            }
        )
    return tuple(events)


def _tool_execution_detail(summary: Mapping[str, object]) -> str:
    for key, singular, plural in (
        ("matched_count", "matching resource", "matching resources"),
        ("resource_count", "resource", "resources"),
        ("total_resources", "resource inspected", "resources inspected"),
        ("metric_checked", "metric checked", "metrics checked"),
    ):
        value = summary.get(key)
        if isinstance(value, int):
            return f"{value} {singular if value == 1 else plural}"
    return f"Status: {str(summary.get('status') or 'unavailable').replace('_', ' ')}"


def _is_explicit_tool_command(prompt: str) -> bool:
    parts = prompt.lstrip().split(maxsplit=1)
    return bool(parts and parts[0] in _EXPLICIT_TOOL_VERBS)


async def _with_web_evidence(
    prompt: str,
    view_context: dict[str, Any],
    resolver: ChatWebSearchEvidenceResolver | None,
    *,
    progress_observer: AgentProgressObserver | None = None,
    allow_agent_request: bool = False,
) -> dict[str, Any]:
    """Replace client-supplied web data with a bounded server-owned snapshot."""

    enriched = dict(view_context)
    enriched.pop("_web_evidence", None)
    if (
        resolver is None
        or "_behavior_evidence" in enriched
        or "_screen_scope" in enriched
        or ("_agent_evidence" in enriched and not allow_agent_request)
        or (_explicit_agent_requested(prompt) and not allow_agent_request)
    ):
        return enriched
    progressive = getattr(resolver, "resolve_with_progress", None)
    evidence = (
        await progressive(
            prompt,
            enriched,
            progress_observer=progress_observer,
        )
        if progress_observer is not None and callable(progressive)
        else await resolver.resolve(prompt, enriched)
    )
    if evidence is not None:
        enriched["_web_evidence"] = dict(evidence)
    return enriched


def merge_evidence_branch_results(
    prompt: str,
    base_context: Mapping[str, Any],
    results: Sequence[EvidenceBranchResult],
    *,
    conversation_context: Mapping[str, str] | None = None,
    target_agent: str | None = None,
    allow_agent_web: bool = False,
) -> dict[str, Any]:
    """Merge immutable branch snapshots with the established authority precedence."""

    results_by_kind = {result.kind: result for result in results}
    contexts = {kind: result.context for kind, result in results_by_kind.items()}
    merged = dict(base_context)

    tool_context = contexts.get(EvidenceBranchKind.TOOL)
    if tool_context is not None and (
        "_tool_evidence" in tool_context or "_current_screen_tool" in tool_context
    ):
        for key in (
            "_behavior_evidence",
            "_operational_evidence",
            "_tool_evidence",
            "_current_screen_tool",
        ):
            if key in tool_context:
                merged[key] = tool_context[key]
            else:
                merged.pop(key, None)

    operational_context = contexts.get(EvidenceBranchKind.OPERATIONAL)
    operational_evidence = (
        operational_context.get("_operational_evidence")
        if operational_context is not None
        else None
    )
    selected_operational = isinstance(operational_evidence, Mapping) and isinstance(
        operational_evidence.get("selected_incident"),
        Mapping,
    )
    implicit_tool = "_tool_evidence" in merged and not _is_explicit_tool_command(prompt)
    if (
        operational_evidence is not None
        and not any(key in merged for key in ("_screen_scope", "_behavior_evidence"))
        and "_current_screen_tool" not in merged
        and ("_tool_evidence" not in merged or (selected_operational and implicit_tool))
    ):
        merged.pop("_tool_evidence", None)
        merged["_operational_evidence"] = operational_evidence

    selected_agent = _selected_agent(prompt, conversation_context, target_agent)
    agent_owned = selected_agent is not None
    preincident_read = parse_preincident_activity(prompt) is not None
    read_investigation = preincident_read or (
        classify_read_investigation_intent(prompt) is not None
        and resource_name_from_question(prompt) is not None
    )
    current_screen_tool = merged.pop("_current_screen_tool", None)
    agent_result = results_by_kind.get(EvidenceBranchKind.AGENT)
    agent_context = agent_result.context if agent_result is not None else None
    agent_evidence = agent_context.get("_agent_evidence") if agent_context is not None else None
    if (
        agent_evidence is None
        and selected_agent is not None
        and agent_result is not None
        and agent_result.status
        in {
            EvidenceBranchStatus.FAILED,
            EvidenceBranchStatus.TIMED_OUT,
            EvidenceBranchStatus.UNAVAILABLE,
        }
    ):
        agent_evidence = _agent_handoff(
            selected_agent,
            reason=(
                "agent_conversational_port_error"
                if agent_result.status is EvidenceBranchStatus.FAILED
                else "agent_conversational_port_unavailable"
            ),
        )
    agent_handoff_only = isinstance(agent_evidence, Mapping) and (
        agent_evidence.get("handoff_from") is not None and agent_evidence.get("answer") is None
    )
    agent_blocked = (
        ("_behavior_evidence" in merged and not agent_owned and not preincident_read)
        or ("_operational_evidence" in merged and not agent_owned)
        or ("_tool_evidence" in merged and not read_investigation and not agent_owned)
        or (current_screen_tool is not None and not agent_owned)
    )
    if agent_evidence is not None and not agent_blocked:
        if (read_investigation or agent_owned) and not agent_handoff_only:
            merged.pop("_tool_evidence", None)
        if (preincident_read or agent_owned) and not agent_handoff_only:
            merged.pop("_behavior_evidence", None)
        if preincident_read and not agent_handoff_only:
            merged.pop("_screen_scope", None)
        if not agent_handoff_only:
            merged.pop("_web_evidence", None)
        merged["_agent_evidence"] = agent_evidence

    web_context = contexts.get(EvidenceBranchKind.PUBLIC_WEB)
    if (
        web_context is not None
        and "_web_evidence" in web_context
        and not any(key in merged for key in ("_behavior_evidence", "_screen_scope"))
        and ("_agent_evidence" not in merged or allow_agent_web)
        and (not _explicit_agent_requested(prompt) or allow_agent_web)
    ):
        merged["_web_evidence"] = web_context["_web_evidence"]
    return merged


def _tool_matches_current_route(
    evidence: Mapping[str, Any],
    view_context: Mapping[str, Any],
) -> bool:
    tool = evidence.get("tool")
    route = str(view_context.get("routeId") or "").lower()
    same_route: dict[str, frozenset[str]] = {
        "get_kpi": frozenset({"dashboard", "overview"}),
        "list_hil": frozenset({"approvals", "hil-queue"}),
        "query_audit": frozenset({"audit"}),
        "list_incidents": frozenset({"incidents"}),
    }
    return isinstance(tool, str) and route in same_route.get(tool, frozenset())


def _delegation_summary(view_context: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the bounded public metadata for one delegated turn."""

    raw = view_context.get("_agent_evidence")
    if not isinstance(raw, Mapping):
        return None
    primary = raw.get("primary_agent")
    if not isinstance(primary, str) or not primary:
        return None
    contributors = raw.get("contributors")
    safe_contributors = (
        [item for item in contributors[:8] if isinstance(item, str)]
        if isinstance(contributors, list)
        else []
    )
    summary: dict[str, Any] = {
        "primary_agent": primary,
        "contributors": safe_contributors,
    }
    trace_ref = raw.get("trace_ref")
    if isinstance(trace_ref, str) and trace_ref:
        summary["trace_ref"] = trace_ref[:256]
    handoff_from = raw.get("handoff_from")
    handoff_reason = raw.get("handoff_reason")
    if isinstance(handoff_from, str) and handoff_from in PANTHEON_NAMES:
        summary["handoff_from"] = handoff_from
    if isinstance(handoff_reason, str) and handoff_reason:
        summary["handoff_reason"] = handoff_reason[:128]
    return summary


def _retrieval_source_previews(
    view_context: Mapping[str, Any],
    *,
    server_owned: bool,
) -> list[dict[str, str]]:
    """Return a bounded, display-safe preview of evidence selected so far."""

    sources: list[dict[str, str]] = []
    route_id = str(view_context.get("routeId") or "").strip()
    if route_id:
        route_label = str(view_context.get("routeLabel") or route_id).strip()
        facts = view_context.get("facts")
        fact_count = len(facts) if isinstance(facts, list) else 0
        sources.append(
            {
                "kind": "screen",
                "label": route_label,
                "detail": f"current screen - {fact_count} facts",
                "side_effect_class": "read",
            }
        )
    if not server_owned:
        return sources

    behavior = view_context.get("_behavior_evidence")
    if isinstance(behavior, Mapping):
        sources.append(
            {
                "kind": "behavior",
                "label": str(behavior.get("behavior_id") or "Behavior knowledge"),
                "detail": str(behavior.get("implementation_status") or behavior.get("status")),
                "side_effect_class": "read",
            }
        )

    tool = view_context.get("_tool_evidence")
    if isinstance(tool, Mapping):
        tool_name = str(tool.get("tool") or "console tool")
        sources.append(
            {
                "kind": "tool",
                "label": tool_name,
                "detail": str(tool.get("authority") or "server read model"),
                "side_effect_class": "read",
            }
        )

    operational = view_context.get("_operational_evidence")
    if isinstance(operational, Mapping):
        selected = operational.get("selected_incident")
        detail = str(operational.get("status") or "operational evidence")
        if isinstance(selected, Mapping):
            detail = str(selected.get("title") or selected.get("correlation_id") or detail)
        sources.append(
            {
                "kind": "operational",
                "label": "Operational evidence",
                "detail": detail,
                "side_effect_class": "read",
            }
        )

    agent = view_context.get("_agent_evidence")
    if isinstance(agent, Mapping):
        primary = str(agent.get("primary_agent") or "Pantheon agent")
        sources.append(
            {
                "kind": "agent",
                "label": primary,
                "detail": "agent-owned domain evidence",
                "side_effect_class": "route",
            }
        )

    concept = view_context.get("_concept_evidence")
    if isinstance(concept, Mapping):
        entries = concept.get("entries")
        terms = (
            [
                str(entry.get("term"))
                for entry in entries[:3]
                if isinstance(entry, Mapping) and entry.get("term")
            ]
            if isinstance(entries, list)
            else []
        )
        sources.append(
            {
                "kind": "glossary",
                "label": "FDAI glossary",
                "detail": ", ".join(terms) or "selected definitions",
                "side_effect_class": "read",
            }
        )

    web = view_context.get("_web_evidence")
    if isinstance(web, Mapping):
        web_sources = web.get("sources")
        if isinstance(web_sources, list):
            for source in web_sources[:3]:
                if not isinstance(source, Mapping):
                    continue
                sources.append(
                    {
                        "kind": "web",
                        "label": str(source.get("title") or source.get("domain") or "Web"),
                        "detail": str(source.get("url") or "public-web evidence"),
                        "side_effect_class": "read",
                    }
                )
    return sources[:8]


def _web_search_summary(view_context: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return public search provenance without echoing untrusted snippet bodies."""

    raw = view_context.get("_web_evidence")
    if not isinstance(raw, Mapping):
        return None
    sources = raw.get("sources")
    safe_sources = (
        [dict(item) for item in sources[:8] if isinstance(item, Mapping)]
        if isinstance(sources, list)
        else []
    )
    summary: dict[str, Any] = {
        "status": str(raw.get("status") or "unavailable"),
        "sources": safe_sources,
    }
    router = raw.get("router")
    if isinstance(router, Mapping):
        summary["router"] = dict(router)
    return summary
