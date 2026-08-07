"""Project and sanitize deterministic inventory evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.compiler import (
    compile_inventory_query,
    is_inventory_question,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryField,
    InventoryOperator,
    InventoryQuery,
    InventoryQueryGrouping,
    InventoryQueryKind,
    InventoryQuerySource,
    inventory_query_matches,
    normalize_inventory_value,
)
from fdai.delivery.operator_api.projections.conversation.inventory.activity import (
    project_inventory_activity,
)
from fdai.delivery.operator_api.projections.conversation.inventory.schedule import (
    ScheduledShutdownEvidenceError,
    project_scheduled_shutdown_result,
)
from fdai.delivery.operator_api.routes.chat_topology_intent import is_topology_question
from fdai.delivery.operator_api.routes.inventory_provider_execution import (
    project_inventory_provider_execution,
)

_MAX_RESOURCES = 40
_MAX_LINKS = 40


def needs_inventory_evidence(prompt: str) -> bool:
    """Return whether a question asks for observed Azure resource inventory."""

    return is_topology_question(prompt) or is_inventory_question(prompt)


def _inventory_interpretation_required(query: InventoryQuery) -> dict[str, Any]:
    return {
        "tool": "query_inventory",
        "authority": "server_inventory_graph",
        "result": {
            "status": "unavailable",
            "reason": "inventory_semantic_interpretation_required",
            "query": query.to_dict(),
        },
    }


def _project_inventory_result(
    prompt: str,
    graph: Mapping[str, Any],
    *,
    activity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    projected = _safe_inventory_payload(graph)
    if projected is None:
        return {"status": "unavailable", "reason": "invalid_inventory_payload"}
    resources, raw_links = projected
    managed = [item for item in resources if item["type"] != "subscription"]
    query = compile_inventory_query(prompt, resources=managed)
    if query is None:
        return {"status": "unavailable", "reason": "inventory_query_unrecognized"}
    return _project_verified_inventory_result(
        query,
        graph,
        activity=activity,
        projected=(resources, raw_links),
    )


def _project_verified_inventory_result(
    query: InventoryQuery,
    graph: Mapping[str, Any],
    *,
    activity: Mapping[str, Any] | None = None,
    projected: tuple[list[dict[str, Any]], Sequence[Any]] | None = None,
) -> dict[str, Any]:
    safe_payload = projected or _safe_inventory_payload(graph)
    if safe_payload is None:
        return {"status": "unavailable", "reason": "invalid_inventory_payload"}
    resources, raw_links = safe_payload
    if query.kind is InventoryQueryKind.SCHEDULED_SHUTDOWN:
        try:
            return project_scheduled_shutdown_result(query, graph, resources)
        except ScheduledShutdownEvidenceError as exc:
            return {
                "status": "unavailable",
                "reason": type(exc).__name__,
                "query": query.to_dict(),
            }
    id_to_name = {str(item["id"]): str(item["name"]) for item in resources}
    managed = [item for item in resources if item["type"] != "subscription"]
    if query.source is InventoryQuerySource.ACTIVITY:
        return project_inventory_activity(query, activity, managed)
    if graph.get("unavailable_reason"):
        provider_execution = project_inventory_provider_execution(graph.get("provider_execution"))
        return {
            "status": "unavailable",
            "reason": str(graph["unavailable_reason"]),
            "query_source": query.source.value,
            "query": query.to_dict(),
            "freshness": _optional_text(graph.get("freshness")),
            **({"provider_execution": provider_execution} if provider_execution else {}),
        }
    matched = [item for item in managed if inventory_query_matches(query, item)]
    provider_type_summary = query.kind is InventoryQueryKind.TYPES and not query.predicates
    scope_counts = query.kind is InventoryQueryKind.SCOPE_COUNTS and not query.predicates
    provider_native_summary = provider_type_summary or scope_counts
    reported_resources = (
        [
            item
            for item in matched
            if item["type"] != "resource-group" and item.get("provider_type") is not None
        ]
        if provider_native_summary
        else matched
    )
    reported_resources = sorted(
        reported_resources,
        key=lambda item: _inventory_resource_sort_key(query, item),
    )
    counted_resources = (
        [item for item in managed if item["type"] != "resource-group"]
        if provider_native_summary
        else managed
    )
    matched_type_counts = Counter(
        str(item.get("provider_type") or item["type"]).casefold() for item in reported_resources
    )
    state_coverage = query.kind is InventoryQueryKind.STATE_COVERAGE
    inventory_coverage = query.kind is InventoryQueryKind.INVENTORY_COVERAGE
    direct_state_sources = {"operational", "power"}
    unavailable_state_resources = [
        item for item in reported_resources if item.get("status_source") not in direct_state_sources
    ]
    available_state_resources = [
        item for item in reported_resources if item.get("status_source") in direct_state_sources
    ]
    links = [
        safe_link
        for item in raw_links
        if isinstance(item, Mapping) and (safe_link := _safe_link(item, id_to_name)) is not None
    ]
    if query.kind is InventoryQueryKind.RELATIONSHIPS and matched:
        names = {str(item["name"]) for item in matched}
        links = [item for item in links if item["source"] in names or item["target"] in names]

    requested_types = _predicate_values(query, InventoryField.RESOURCE_TYPE)
    status_filter = _predicate_values(query, InventoryField.STATUS)
    group_filter = _single_predicate_value(query, InventoryField.RESOURCE_GROUP)
    name_filter = _single_predicate_value(query, InventoryField.NAME)
    workload_query = query.include_workloads and "kubernetes-cluster" in requested_types
    provider_execution = project_inventory_provider_execution(graph.get("provider_execution"))
    return {
        "status": "partial" if workload_query else "matched",
        "query_source": query.source.value,
        "query_kind": query.kind.value,
        "query_scope": query.scope.value,
        "group_by": query.group_by.value,
        "display_projection": (
            "status_groups"
            if query.group_by is InventoryQueryGrouping.STATUS
            else query.projection.value
        ),
        "query": query.to_dict(),
        "requested_types": list(requested_types),
        "status_filter": list(status_filter),
        "status_coverage": (
            {
                "included": ["normalized_current_operational_status"],
                "excluded": ["deployment_failures", "activity_failures"],
            }
            if status_filter
            else None
        ),
        "status_groups": [
            {"id": group.id, "values": list(group.values)} for group in query.status_groups
        ],
        "resource_group": group_filter,
        "name_filter": name_filter,
        "provider_type_summary": provider_type_summary,
        "scope_counts": scope_counts,
        "state_coverage": state_coverage,
        "inventory_coverage": inventory_coverage,
        "inventory_coverage_complete": not bool(graph.get("truncated")),
        "inventory_checked_type_counts": dict(sorted(matched_type_counts.items())),
        "inventory_failed_type_count": 0,
        "state_unavailable_resource_count": len(unavailable_state_resources),
        "state_unavailable_type_counts": dict(
            sorted(
                Counter(
                    str(item.get("provider_type") or item["type"]).casefold()
                    for item in unavailable_state_resources
                ).items()
            )
        ),
        "state_available_type_counts": dict(
            sorted(
                Counter(
                    str(item.get("provider_type") or item["type"]).casefold()
                    for item in available_state_resources
                ).items()
            )
        ),
        "resource_group_count": sum(item["type"] == "resource-group" for item in managed),
        "derived_resource_count": sum(
            item["type"] != "resource-group" and item.get("provider_type") is None
            for item in managed
        ),
        "snapshot_at": _optional_text(graph.get("snapshot_at")),
        "freshness": _optional_text(graph.get("freshness")),
        "source": _optional_text(graph.get("source")),
        **({"provider_execution": provider_execution} if provider_execution else {}),
        "active_view": _optional_text(graph.get("active_view")) or "provider-default",
        "truncated": bool(graph.get("truncated")),
        "total_resources": len(managed),
        "matched_count": len(reported_resources),
        "type_counts": dict(
            sorted(
                Counter(
                    str(item.get("provider_type") or item["type"]).casefold()
                    for item in counted_resources
                ).items()
            )
        ),
        "matched_type_counts": dict(sorted(matched_type_counts.items())),
        "matched_location_counts": dict(
            sorted(
                Counter(
                    str(item.get("location") or "unknown") for item in reported_resources
                ).items()
            )
        ),
        "matched_status_counts": dict(
            sorted(
                Counter(str(item.get("status") or "unknown") for item in reported_resources).items()
            )
        ),
        "resources": [
            {key: value for key, value in item.items() if key != "id"}
            for item in reported_resources[:_MAX_RESOURCES]
        ],
        "links": links[:_MAX_LINKS] if query.kind is InventoryQueryKind.RELATIONSHIPS else [],
        "coverage_gap": "kubernetes_workloads" if workload_query else None,
        "state_history_requested": query.require_state_history,
    }


def _inventory_resource_sort_key(
    query: InventoryQuery,
    resource: Mapping[str, Any],
) -> tuple[str, str, str, str]:
    group_field = {
        InventoryQueryGrouping.RESOURCE_TYPE: "provider_type",
        InventoryQueryGrouping.STATUS: "status",
        InventoryQueryGrouping.LOCATION: "location",
    }.get(query.group_by)
    group_value = resource.get(group_field) if group_field else ""
    return (
        normalize_inventory_value(group_value or ""),
        normalize_inventory_value(resource.get("name") or ""),
        normalize_inventory_value(resource.get("resource_group") or ""),
        normalize_inventory_value(resource.get("type") or ""),
    )


def _safe_inventory_payload(
    graph: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Sequence[Any]] | None:
    raw_resources = graph.get("resources")
    raw_links = graph.get("links")
    if not isinstance(raw_resources, (list, tuple)) or not isinstance(raw_links, (list, tuple)):
        return None
    resources: list[dict[str, Any]] = []
    raw_by_id: dict[str, Mapping[str, Any]] = {}
    for raw in raw_resources:
        if not isinstance(raw, Mapping):
            return None
        resource = _safe_resource(raw)
        if resource is None:
            return None
        resources.append(resource)
        raw_by_id[resource["id"]] = raw
    safe_by_id = {resource["id"]: resource for resource in resources}
    for resource in resources:
        if resource["resource_group"] is not None:
            continue
        if resource["type"] == "resource-group":
            resource["resource_group"] = resource["name"]
            continue
        parent_id = raw_by_id[resource["id"]].get("parent_id")
        parent = safe_by_id.get(str(parent_id))
        if parent is not None and parent["type"] == "resource-group":
            resource["resource_group"] = parent["name"]
    return resources, raw_links


def inventory_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Return bounded evidence references for inventory and workload observations."""

    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    source = result.get("source")
    snapshot = result.get("snapshot_at")
    prefix = (
        "activity"
        if result.get("query_source") == InventoryQuerySource.ACTIVITY.value
        else "inventory"
    )
    refs = [f"{prefix}:{source}@{snapshot}"] if source and snapshot else []
    workload = result.get("workload")
    if isinstance(workload, Mapping):
        workload_source = workload.get("source")
        observed_at = workload.get("observed_at")
        if workload_source and observed_at:
            refs.append(f"kubernetes:{workload_source}@{observed_at}")
    return tuple(refs)


def partial_inventory_findings_are_grounded(evidence: Mapping[str, Any]) -> bool:
    """Return whether partial inventory has positive state-filtered resource findings."""

    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "partial":
        return False
    matched_count = result.get("matched_count")
    status_filter = result.get("status_filter")
    return (
        isinstance(matched_count, int)
        and not isinstance(matched_count, bool)
        and matched_count > 0
        and isinstance(status_filter, list)
        and bool(status_filter)
    )


def _safe_resource(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    resource_id = raw.get("id")
    resource_type = raw.get("type")
    name = raw.get("name")
    if not all(isinstance(value, str) and value for value in (resource_id, resource_type, name)):
        return None
    raw_props = raw.get("props")
    props: Mapping[str, Any] = raw_props if isinstance(raw_props, Mapping) else {}
    return {
        "id": resource_id,
        "type": resource_type,
        "provider_type": _optional_text(props.get("providerType") or raw.get("provider_type")),
        "name": name,
        "status": str(raw.get("status") or "unknown"),
        "status_source": str(raw.get("status_source") or "unknown"),
        "location": _optional_text(props.get("location") or raw.get("location")),
        "resource_group": _optional_text(props.get("resourceGroup") or raw.get("resource_group")),
        "scheduled_shutdown_status": _optional_text(raw.get("scheduled_shutdown_status")),
        "scheduled_shutdown_time": _optional_text(raw.get("scheduled_shutdown_time")),
        "scheduled_shutdown_time_zone": _optional_text(raw.get("scheduled_shutdown_time_zone")),
        "scheduled_shutdown_time_zone_iana": _optional_text(
            raw.get("scheduled_shutdown_time_zone_iana")
        ),
        "scheduled_shutdown_target_name": _optional_text(raw.get("scheduled_shutdown_target_name")),
        "scheduled_shutdown_target_resource_group": _optional_text(
            raw.get("scheduled_shutdown_target_resource_group")
        ),
        "scheduled_shutdown_target_subscription_digest": _optional_text(
            raw.get("scheduled_shutdown_target_subscription_digest")
        ),
    }


def _safe_link(raw: Mapping[str, Any], id_to_name: Mapping[str, str]) -> dict[str, str] | None:
    source = id_to_name.get(str(raw.get("source")))
    target = id_to_name.get(str(raw.get("target")))
    link_type = raw.get("type")
    if source is None or target is None or not isinstance(link_type, str):
        return None
    return {"source": source, "target": target, "type": link_type}


def _predicate_values(query: InventoryQuery, field: InventoryField) -> tuple[str, ...]:
    predicate = next(
        (
            item
            for item in query.predicates
            if item.field is field and item.operator in {InventoryOperator.EQ, InventoryOperator.IN}
        ),
        None,
    )
    if predicate is None:
        return ()
    if predicate.operator is InventoryOperator.IN and isinstance(predicate.value, tuple):
        return predicate.value
    return (predicate.value,) if isinstance(predicate.value, str) else ()


def _single_predicate_value(query: InventoryQuery, field: InventoryField) -> str | None:
    values = _predicate_values(query, field)
    return values[0] if len(values) == 1 else None


def _optional_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
