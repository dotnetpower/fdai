"""Pure provenance previews for enriched chat evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.agents import PANTHEON_NAMES


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
