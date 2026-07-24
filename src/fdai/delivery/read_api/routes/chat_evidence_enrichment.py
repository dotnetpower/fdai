"""Server-owned evidence enrichment and response provenance helpers."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from inspect import Parameter, signature
from typing import Any, Protocol

from fdai.agents import PANTHEON_NAMES
from fdai.core.conversation.narrator import default_tool_schemas
from fdai.delivery.read_api.routes.chat_data_sources import needs_read_source_evidence
from fdai.delivery.read_api.routes.chat_evidence import needs_operational_evidence
from fdai.delivery.read_api.routes.chat_inventory import needs_inventory_evidence
from fdai.delivery.read_api.routes.chat_prompt import (
    _AGENT_NAME_TOKEN,
    _CONCEPT_DOMAIN,
    _is_concept_query,
)
from fdai.delivery.read_api.routes.chat_subscription_health import needs_subscription_health


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


class ChatWebSearchEvidenceResolver(Protocol):
    """Read-only public-web evidence resolver for explicitly eligible turns."""

    async def resolve(
        self,
        prompt: str,
        view_context: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...


_VIEW_EXPLANATION_INTENT = re.compile(
    r"\b(connect(?:ed|s|ion)?|relationship|relate[ds]?|create[ds]?|creation|criteri(?:a|on)|"
    r"owner|ownership|dedup(?:e|lication)?|repeat|close[ds]?|closure|provenance|source|why)\b"
    "|연결|관계|생성|기준|소유|담당|중복|반복|종료|닫|출처|근거|왜",
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
    if resolver is None:
        return enriched
    evidence = await resolver.resolve(prompt)
    if evidence is not None:
        enriched["_behavior_evidence"] = dict(evidence)
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
    effective_context = conversation_context or _trace_incident_context(enriched)
    if (
        resolver is None
        or "_behavior_evidence" in enriched
        or (effective_context is None and not needs_operational_evidence(prompt, enriched))
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


def _trace_incident_context(view_context: Mapping[str, Any]) -> dict[str, str] | None:
    """Return a bounded selection hint for a Trace screen correlation."""

    if str(view_context.get("routeId") or "").lower() != "trace":
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
    progress_observer: AgentProgressObserver | None = None,
) -> dict[str, Any]:
    """Replace client-supplied delegation data with a server-owned result."""

    enriched = dict(view_context)
    enriched.pop("_agent_evidence", None)
    current_screen_tool = enriched.pop("_current_screen_tool", None)
    explicit_agent = _explicit_agent_requested(prompt)
    if (
        delegate is None
        or "_behavior_evidence" in enriched
        or "_operational_evidence" in enriched
        or "_tool_evidence" in enriched
        or current_screen_tool is not None
        or _uses_view_explanations(prompt, enriched)
        or (_is_concept_query(prompt) and _CONCEPT_DOMAIN.search(prompt) and not explicit_agent)
    ):
        return enriched
    progressive = getattr(delegate, "delegate_with_progress", None)
    evidence = (
        await progressive(
            prompt=prompt,
            user_id=user_id,
            session_id=session_id,
            progress_observer=progress_observer,
        )
        if progress_observer is not None and callable(progressive)
        else await delegate.delegate(
            prompt=prompt,
            user_id=user_id,
            session_id=session_id,
        )
    )
    if evidence is not None:
        enriched["_agent_evidence"] = dict(evidence)
    return enriched


def _explicit_agent_requested(prompt: str) -> bool:
    names = {name.lower() for name in PANTHEON_NAMES}
    return any(token.lower() in names for token in _AGENT_NAME_TOKEN.findall(prompt))


async def _with_tool_evidence(
    prompt: str,
    view_context: dict[str, Any],
    resolver: ChatToolResolver | None,
    *,
    principal_id: str,
    progress_observer: AgentProgressObserver | None = None,
) -> dict[str, Any]:
    """Replace client-supplied tool output with a server-owned result."""

    enriched = dict(view_context)
    enriched.pop("_tool_evidence", None)
    enriched.pop("_current_screen_tool", None)
    explicit_command = _is_explicit_tool_command(prompt)
    inventory_question = needs_inventory_evidence(prompt)
    subscription_health_question = needs_subscription_health(prompt)
    read_source_question = needs_read_source_evidence(prompt)
    if resolver is None or (
        not explicit_command
        and not inventory_question
        and not subscription_health_question
        and not read_source_question
        and ("_behavior_evidence" in enriched or "_operational_evidence" in enriched)
    ):
        return enriched
    progressive = getattr(resolver, "resolve_with_progress", None)
    evidence = (
        await progressive(
            prompt,
            principal_id=principal_id,
            progress_observer=progress_observer,
        )
        if progress_observer is not None and callable(progressive)
        else await resolver.resolve(prompt, principal_id=principal_id)
    )
    if evidence is not None:
        if explicit_command or evidence.get("tool") in {
            "describe_read_sources",
            "get_current_time",
            "query_inventory",
            "query_subscription_health",
        }:
            enriched.pop("_behavior_evidence", None)
            enriched.pop("_operational_evidence", None)
        if _tool_matches_current_route(evidence, enriched):
            enriched["_current_screen_tool"] = evidence.get("tool")
        else:
            enriched["_tool_evidence"] = dict(evidence)
    return enriched


def _is_explicit_tool_command(prompt: str) -> bool:
    parts = prompt.lstrip().split(maxsplit=1)
    return bool(parts and parts[0] in _EXPLICIT_TOOL_VERBS)


async def _with_web_evidence(
    prompt: str,
    view_context: dict[str, Any],
    resolver: ChatWebSearchEvidenceResolver | None,
    *,
    progress_observer: AgentProgressObserver | None = None,
) -> dict[str, Any]:
    """Replace client-supplied web data with a bounded server-owned snapshot."""

    enriched = dict(view_context)
    enriched.pop("_web_evidence", None)
    if resolver is None or "_behavior_evidence" in enriched:
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
