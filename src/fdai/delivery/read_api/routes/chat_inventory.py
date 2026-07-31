"""Deterministic Azure inventory evidence and answers for Command Deck."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from fdai.delivery.read_api.routes.chat_inventory_activity import (
    MAX_ACTIVITY_EVENTS,
    project_inventory_activity,
    render_inventory_activity,
)
from fdai.delivery.read_api.routes.chat_inventory_compiler import (
    compile_inventory_query,
    inventory_query_scope,
    is_inventory_question,
)
from fdai.delivery.read_api.routes.chat_inventory_followup import (
    SUBSCRIPTION_ROOT,
    SUBSCRIPTION_ROOT_LIMIT,
)
from fdai.delivery.read_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryQuery,
    InventoryQueryGrouping,
    InventoryQueryKind,
    InventoryQueryScope,
    InventoryQuerySource,
    inventory_query_argument_schema,
    inventory_query_matches,
    normalize_inventory_value,
)
from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver
from fdai.delivery.read_api.routes.chat_turn_plan import TurnTool
from fdai.delivery.read_api.routes.inventory_graph import InventoryGraphProvider

_MAX_RESOURCES = 40
_MAX_LINKS = 40
KubernetesWorkloadProvider = Callable[[], Awaitable[Mapping[str, Any]]]
InventoryActivityProvider = Callable[[int, int], Awaitable[Mapping[str, Any]]]


@runtime_checkable
class InventoryRefreshBarrier(Protocol):
    async def wait_for_refresh(self) -> None: ...


@dataclass(frozen=True, slots=True)
class InventoryChatTools:
    """Resolve Azure resource questions from the authoritative graph provider."""

    provider: InventoryGraphProvider
    fallback: ChatToolResolver | None = None
    workload_provider: KubernetesWorkloadProvider | None = None
    activity_provider: InventoryActivityProvider | None = None

    def turn_tools(self) -> tuple[TurnTool, ...]:
        """Return the strict semantic capability for generalized resource reads."""

        return (
            TurnTool(
                name="query_inventory",
                description=(
                    "Read current resources or bounded resource changes with verified predicates."
                ),
                side_effect_class="read",
                argument_schema=inventory_query_argument_schema(),
            ),
        )

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        """Execute one verified semantic inventory plan without reclassifying text."""

        del principal_id
        if tool_name != "query_inventory":
            return None
        query = InventoryQuery.from_mapping(arguments)
        return await self._resolve_query(query)

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if not needs_inventory_evidence(prompt):
            return await self._fallback(prompt, principal_id=principal_id)
        try:
            graph = await self._graph_for_scope(inventory_query_scope(prompt))
            safe_payload = _safe_inventory_payload(graph)
            if safe_payload is None:
                raise ValueError("invalid_inventory_payload")
            resources, raw_links = safe_payload
            managed = [item for item in resources if item["type"] != "subscription"]
            query = compile_inventory_query(prompt, resources=managed)
            if query is None:
                return await self._fallback(prompt, principal_id=principal_id)
            if query.require_fresh and graph.get("freshness") != "fresh":
                graph = await self._graph_for_query(query, graph=graph)
                safe_payload = _safe_inventory_payload(graph)
                if safe_payload is None:
                    raise ValueError("invalid_inventory_payload")
                resources, raw_links = safe_payload
            activity = await self._activity(query)
            result = _project_verified_inventory_result(
                query,
                graph,
                activity=activity,
                projected=(resources, raw_links),
            )
            if result.get("coverage_gap") == "kubernetes_workloads":
                result = await self._resolve_workloads(result)
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_inventory",
            "authority": (
                "server_inventory_activity"
                if result.get("query_source") == InventoryQuerySource.ACTIVITY.value
                else "server_inventory_graph"
            ),
            "result": result,
        }

    async def _resolve_query(
        self,
        query: InventoryQuery,
        *,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        graph = await self._graph_for_query(query)
        activity = await self._activity(query)
        result = (
            _project_inventory_result(prompt, graph, activity=activity)
            if prompt is not None
            else _project_verified_inventory_result(query, graph, activity=activity)
        )
        return {
            "tool": "query_inventory",
            "authority": (
                "server_inventory_activity"
                if query.source is InventoryQuerySource.ACTIVITY
                else "server_inventory_graph"
            ),
            "result": result,
        }

    async def _graph_for_query(
        self,
        query: InventoryQuery,
        *,
        graph: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        graph = graph or await self._graph_for_scope(query.scope)
        if query.require_fresh and graph.get("freshness") != "fresh":
            if isinstance(self.provider, InventoryRefreshBarrier):
                await self.provider.wait_for_refresh()
                graph = await self._graph_for_scope(query.scope)
            if graph.get("freshness") != "fresh":
                return {
                    **graph,
                    "resources": [],
                    "links": [],
                    "freshness": str(graph.get("freshness") or "unknown"),
                    "unavailable_reason": "fresh_inventory_required",
                }
        return graph

    async def _graph_for_scope(self, scope: InventoryQueryScope) -> dict[str, Any]:
        if scope is InventoryQueryScope.SUBSCRIPTION:
            graph = dict(
                await self.provider(
                    None,
                    4,
                    ("contains", "attached_to", "depends_on"),
                    root=SUBSCRIPTION_ROOT,
                    limit=SUBSCRIPTION_ROOT_LIMIT,
                )
            )
        else:
            graph = dict(await self.provider(None, 4, ("contains", "attached_to", "depends_on")))
        return graph

    async def _activity(self, query: InventoryQuery) -> Mapping[str, Any] | None:
        if query.source is not InventoryQuerySource.ACTIVITY:
            return None
        if self.activity_provider is None:
            return {"status": "unavailable", "reason": "activity_provider_unavailable"}
        return dict(
            await self.activity_provider(
                query.lookback_seconds or 0,
                MAX_ACTIVITY_EVENTS,
            )
        )

    async def _resolve_workloads(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.workload_provider is None:
            return result
        try:
            workload = dict(await self.workload_provider())
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result["workload_evidence_status"] = "unavailable"
            result["workload_evidence_reason"] = type(exc).__name__
            return result
        cluster_names = {
            str(item.get("name"))
            for item in result.get("resources", ())
            if isinstance(item, Mapping) and item.get("type") == "kubernetes-cluster"
        }
        if workload.get("status") != "matched" or workload.get("cluster_name") not in cluster_names:
            result["workload_evidence_status"] = "unmatched"
            return result
        if not isinstance(workload.get("deployments"), (list, tuple)) or not isinstance(
            workload.get("pods"), (list, tuple)
        ):
            result["workload_evidence_status"] = "invalid"
            return result
        result["workload"] = workload
        uncovered_cluster_count = len(cluster_names - {str(workload["cluster_name"])})
        if uncovered_cluster_count or bool(workload.get("truncated")):
            result["workload_evidence_status"] = "partial"
            result["uncovered_cluster_count"] = uncovered_cluster_count
            return result
        result["status"] = "matched"
        result["coverage_gap"] = None
        return result

    async def _fallback(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if self.fallback is None:
            return None
        return await self.fallback.resolve(prompt, principal_id=principal_id)


def needs_inventory_evidence(prompt: str) -> bool:
    """Return whether a question asks for observed Azure resource inventory."""

    return is_inventory_question(prompt)


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
    id_to_name = {str(item["id"]): str(item["name"]) for item in resources}
    managed = [item for item in resources if item["type"] != "subscription"]
    if query.source is InventoryQuerySource.ACTIVITY:
        return project_inventory_activity(query, activity, managed)
    if graph.get("unavailable_reason"):
        return {
            "status": "unavailable",
            "reason": str(graph["unavailable_reason"]),
            "query_source": query.source.value,
            "query": query.to_dict(),
            "freshness": _optional_text(graph.get("freshness")),
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
    counted_resources = (
        [item for item in managed if item["type"] != "resource-group"]
        if provider_native_summary
        else managed
    )
    matched_type_counts = Counter(
        str(item.get("provider_type") or item["type"]).casefold() for item in reported_resources
    )
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
        "resource_group_count": sum(item["type"] == "resource-group" for item in managed),
        "derived_resource_count": sum(
            item["type"] != "resource-group" and item.get("provider_type") is None
            for item in managed
        ),
        "snapshot_at": _optional_text(graph.get("snapshot_at")),
        "freshness": _optional_text(graph.get("freshness")),
        "source": _optional_text(graph.get("source")),
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


def _safe_inventory_payload(
    graph: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Sequence[Any]] | None:
    raw_resources = graph.get("resources")
    raw_links = graph.get("links")
    if not isinstance(raw_resources, (list, tuple)) or not isinstance(raw_links, (list, tuple)):
        return None
    resources = [
        resource
        for raw in raw_resources
        if isinstance(raw, Mapping) and (resource := _safe_resource(raw)) is not None
    ]
    return resources, raw_links


def render_inventory_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
    answer_format: str | None = None,
) -> str | None:
    """Render one inventory tool result without model inference."""

    if evidence.get("tool") != "query_inventory":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if result.get("query_source") == InventoryQuerySource.ACTIVITY.value:
        return render_inventory_activity(result, korean=korean)
    if result.get("status") not in {"matched", "partial"}:
        return (
            "Azure 인벤토리 근거를 조회할 수 없어 리소스 상태를 확정하지 않았습니다."
            if korean
            else "Azure inventory evidence is unavailable, so resource state was not confirmed."
        )

    count = int(result.get("matched_count", 0))
    total = int(result.get("total_resources", 0))
    resources = [item for item in result.get("resources", []) if isinstance(item, Mapping)]
    source = str(result.get("source") or "inventory provider")
    snapshot = str(result.get("snapshot_at") or "unknown time")
    freshness = str(result.get("freshness") or "unknown")
    active_view = str(result.get("active_view") or "provider-default")
    truncated = bool(result.get("truncated"))
    provider_type_summary = bool(result.get("provider_type_summary"))
    scope_counts = bool(result.get("scope_counts"))
    type_counts = result.get("matched_type_counts")
    type_count = len(type_counts) if isinstance(type_counts, Mapping) else 0
    resource_group_count = int(result.get("resource_group_count") or 0)
    derived_resource_count = int(result.get("derived_resource_count") or 0)

    if scope_counts:
        if korean:
            lines = [
                f"관리 범위에서 Azure 리소스 {count}개와 resource group "
                f"{resource_group_count}개를 확인했습니다."
            ]
            lines.append(
                f"Topology에서 파생된 하위 리소스 {derived_resource_count}개는 "
                "provider-native 합계와 분리했습니다."
            )
        else:
            lines = [
                f"The managed scope contains {count} Azure resources and "
                f"{resource_group_count} resource groups."
            ]
            lines.append(
                f"{derived_resource_count} topology-derived child resources were kept "
                "outside the provider-native total."
            )
        lines.append(_inventory_evidence_line(source, snapshot, freshness, korean=korean))
        if truncated:
            lines.append(
                "인벤토리 snapshot이 잘렸으므로 실제 리소스 수가 더 많을 수 있습니다."
                if korean
                else "The inventory snapshot is truncated, so additional resources may exist."
            )
        return "\n".join(lines)

    if answer_format == "table":
        return _render_inventory_table_answer(
            resources,
            korean=korean,
            count=count,
            total=total,
            active_view=active_view,
            source=source,
            snapshot=snapshot,
            freshness=freshness,
            truncated=truncated,
        )
    if answer_format == "chart":
        return _render_inventory_chart_answer(
            result,
            korean=korean,
            count=count,
            total=total,
            active_view=active_view,
            source=source,
            snapshot=snapshot,
            freshness=freshness,
            truncated=truncated,
        )

    if korean:
        lines = (
            [
                f"현재 Azure inventory view '{active_view}'의 inventory record {total}개 중 "
                f"Azure 리소스 {count}개를 {type_count}개 provider type으로 확인했습니다."
            ]
            if provider_type_summary
            else [
                f"현재 Azure inventory view '{active_view}'의 {total}개 중 "
                f"질문과 일치하는 리소스는 {count}개입니다."
            ]
        )
        lines.extend(_answer_detail_lines(result, resources, korean=True))
        if provider_type_summary:
            lines.append(
                f"Resource group {resource_group_count}개는 리소스 합계와 분리해 확인했습니다."
            )
            lines.append(
                f"Topology에서 파생된 하위 리소스 {derived_resource_count}개도 "
                "provider-native 합계와 분리했습니다."
            )
        if result.get("status_coverage"):
            lines.append(
                "이 결과는 정규화된 현재 operational status만 확인합니다. "
                "실패한 deployment 또는 Activity Log 작업이 없다는 뜻은 아닙니다."
            )
        if result.get("status") == "partial":
            workload = result.get("workload")
            if isinstance(workload, Mapping):
                lines.append(_partial_workload_gap(result, workload, korean=True))
            else:
                lines.append(
                    "이 Azure inventory 근거는 AKS 클러스터 리소스 상태까지만 포함하며, "
                    "클러스터 내부 Node readiness, Deployment와 Pod는 포함하지 않습니다. 따라서 "
                    "노드 및 앱 상태는 Kubernetes workload 근거가 연결되기 전에는 "
                    "확정할 수 없습니다."
                )
        if result.get("state_history_requested"):
            lines.append(
                "현재 snapshot은 상태가 시작된 시각을 증명하지 않습니다. 상태 전이 시각은 "
                "Kubernetes event 또는 다른 이력 근거가 연결되기 전에는 확정할 수 없습니다."
            )
        lines.append(f"근거: {source}, snapshot {snapshot}, freshness {freshness}.")
        if truncated:
            lines.append("인벤토리 snapshot이 잘렸으므로 실제 리소스 수가 더 많을 수 있습니다.")
        return "\n".join(lines)

    lines = (
        [
            f"{count} of {total} inventory records in Azure inventory view '{active_view}' are "
            f"Azure resources across {type_count} provider types."
        ]
        if provider_type_summary
        else [
            f"{count} of {total} resources in Azure inventory view "
            f"'{active_view}' match the question."
        ]
    )
    lines.extend(_answer_detail_lines(result, resources, korean=False))
    if provider_type_summary:
        lines.append(
            f"{resource_group_count} resource groups were checked separately "
            "from the resource total."
        )
        lines.append(
            f"{derived_resource_count} topology-derived child resources were also kept "
            "outside the provider-native total."
        )
    if result.get("status_coverage"):
        lines.append(
            "This result checks normalized current operational status only. It does not prove "
            "that no deployment or Activity Log operation failed."
        )
    if result.get("status") == "partial":
        workload = result.get("workload")
        if isinstance(workload, Mapping):
            lines.append(_partial_workload_gap(result, workload, korean=False))
        else:
            lines.append(
                "This Azure inventory evidence covers AKS cluster resources only; it does not "
                "include in-cluster node readiness, Deployments, or Pods. Node and application "
                "health cannot be confirmed until Kubernetes workload evidence is connected."
            )
    if result.get("state_history_requested"):
        lines.append(
            "The current snapshot does not establish when the state began. State-transition "
            "time remains unconfirmed until Kubernetes events or other history evidence is "
            "connected."
        )
    lines.append(f"Evidence: {source}, snapshot {snapshot}, freshness {freshness}.")
    if truncated:
        lines.append("The inventory snapshot is truncated, so additional resources may exist.")
    return "\n".join(lines)


def inventory_execution_query(evidence: Mapping[str, Any]) -> str:
    """Return the lossless typed query that actually selected inventory evidence."""

    result = evidence.get("result")
    safe_result = result if isinstance(result, Mapping) else {}
    raw_query = safe_result.get("query")
    query: dict[str, object] | None = None
    if isinstance(raw_query, Mapping):
        try:
            query = InventoryQuery.from_mapping(raw_query).to_dict()
        except ValueError:
            query = None
    snapshot = {
        key: value
        for key, value in {
            "source": _optional_text(safe_result.get("source")),
            "at": _optional_text(safe_result.get("snapshot_at")),
            "freshness": _optional_text(safe_result.get("freshness")),
            "active_view": _optional_text(safe_result.get("active_view")),
        }.items()
        if value is not None
    }
    projection: dict[str, object] = {
        "operation": "query_inventory",
        "authority": str(evidence.get("authority") or "server_inventory_graph"),
        "query": query,
        "result": {
            "status": str(safe_result.get("status") or "unavailable"),
            "matched_count": _safe_nonnegative_int(safe_result.get("matched_count")),
            "truncated": bool(safe_result.get("truncated")),
        },
        "snapshot": snapshot,
    }
    return json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True)


def _safe_nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _render_inventory_table_answer(
    resources: list[Mapping[str, Any]],
    *,
    korean: bool,
    count: int,
    total: int,
    active_view: str,
    source: str,
    snapshot: str,
    freshness: str,
    truncated: bool,
) -> str:
    lead = (
        f"현재 Azure inventory view '{active_view}'의 {total}개 중 {count}개가 일치합니다."
        if korean
        else f"{count} of {total} resources in Azure inventory view '{active_view}' match."
    )
    headers = (
        ("이름", "형식", "상태", "위치", "리소스 그룹")
        if korean
        else ("Name", "Type", "Status", "Location", "Resource group")
    )
    lines = [lead, "", "| " + " | ".join(headers) + " |", "| --- | --- | --- | --- | --- |"]
    lines.extend(
        "| "
        + " | ".join(
            _markdown_cell(item.get(field) or "-")
            for field in ("name", "type", "status", "location", "resource_group")
        )
        + " |"
        for item in resources
    )
    if count > len(resources):
        lines.extend(
            (
                "",
                f"표에는 최대 {len(resources)}개를 표시했습니다."
                if korean
                else f"The table shows the first {len(resources)} matched resources.",
            )
        )
    lines.extend(("", _inventory_evidence_line(source, snapshot, freshness, korean=korean)))
    if truncated:
        lines.append(
            "인벤토리 snapshot이 잘렸으므로 실제 리소스 수가 더 많을 수 있습니다."
            if korean
            else "The inventory snapshot is truncated, so additional resources may exist."
        )
    return "\n".join(lines)


def _render_inventory_chart_answer(
    result: Mapping[str, Any],
    *,
    korean: bool,
    count: int,
    total: int,
    active_view: str,
    source: str,
    snapshot: str,
    freshness: str,
    truncated: bool,
) -> str:
    query_kind = str(result.get("query_kind") or "list")
    requested_types = result.get("requested_types")
    if query_kind == "types":
        counts = result.get("matched_type_counts")
        title = "리소스 형식별 수" if korean else "Resources by type"
    elif isinstance(requested_types, list) and requested_types == ["resource-group"]:
        counts = result.get("matched_location_counts")
        title = "위치별 리소스 그룹" if korean else "Resource groups by location"
    else:
        counts = result.get("matched_type_counts")
        title = "일치 리소스 형식별 수" if korean else "Matched resources by type"
    safe_counts = counts if isinstance(counts, Mapping) else {}
    sorted_counts = sorted(
        (
            (str(label), value)
            for label, value in safe_counts.items()
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        ),
        key=lambda item: (-item[1], item[0]),
    )
    data = [{"label": label, "value": value} for label, value in sorted_counts[:_MAX_RESOURCES]]
    spec = {
        "type": "bar",
        "title": title,
        "unit": "개" if korean else "resources",
        "data": data,
    }
    lead = (
        f"현재 Azure inventory view '{active_view}'의 {total}개 중 {count}개가 일치합니다."
        if korean
        else f"{count} of {total} resources in Azure inventory view '{active_view}' match."
    )
    lines = [
        lead,
        "",
        "```chart",
        json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
        "```",
        "",
        _inventory_evidence_line(source, snapshot, freshness, korean=korean),
    ]
    if truncated:
        lines.append(
            "인벤토리 snapshot이 잘렸으므로 그래프도 부분 근거입니다."
            if korean
            else "The inventory snapshot is truncated, so the chart is partial evidence."
        )
    return "\n".join(lines)


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _inventory_evidence_line(
    source: str,
    snapshot: str,
    freshness: str,
    *,
    korean: bool,
) -> str:
    prefix = "근거" if korean else "Evidence"
    return f"{prefix}: {source}, snapshot {snapshot}, freshness {freshness}."


def _answer_detail_lines(
    result: Mapping[str, Any],
    resources: list[Mapping[str, Any]],
    *,
    korean: bool,
) -> list[str]:
    workload = result.get("workload")
    if isinstance(workload, Mapping):
        return _workload_lines(workload, korean=korean)
    query_kind = str(result.get("query_kind") or "list")
    if query_kind == "list" and result.get("display_projection") == "names":
        return [f"- {item.get('name')}" for item in resources]
    if query_kind == "list" and result.get("display_projection") == "status_groups":
        return _status_group_lines(result, resources, korean=korean)
    if query_kind == "types":
        counts = result.get("matched_type_counts", {})
        return (
            [f"- {kind}: {value}{'개' if korean else ''}" for kind, value in counts.items()]
            if isinstance(counts, Mapping)
            else []
        )
    if query_kind == "relationships":
        links = [item for item in result.get("links", []) if isinstance(item, Mapping)]
        return [
            f"- {item.get('source')} --{item.get('type')}--> {item.get('target')}" for item in links
        ]
    if query_kind == "count":
        return []
    if query_kind == "scope_counts":
        return []
    return [_resource_line(item, korean=korean) for item in resources]


def _status_group_lines(
    result: Mapping[str, Any],
    resources: list[Mapping[str, Any]],
    *,
    korean: bool,
) -> list[str]:
    raw_groups = result.get("status_groups")
    groups = (
        [item for item in raw_groups if isinstance(item, Mapping)]
        if isinstance(raw_groups, list)
        else []
    )
    lines: list[str] = []
    for group in groups:
        group_id = str(group.get("id") or "unknown")
        raw_values = group.get("values")
        values = {str(value) for value in raw_values} if isinstance(raw_values, list) else set()
        lines.append(f"**{group_id.title()}**")
        matched = [
            item
            for item in resources
            if normalize_inventory_value(item.get("status")).rsplit(" ", 1)[-1] in values
        ]
        if matched:
            lines.extend(_resource_line(item, korean=korean) for item in matched)
        else:
            lines.append(
                "- 이 범위에서 일치하는 리소스가 없습니다."
                if korean
                else "- No matching resources in this scope."
            )
    return lines


def _workload_lines(workload: Mapping[str, Any], *, korean: bool) -> list[str]:
    deployments = [item for item in workload.get("deployments", ()) if isinstance(item, Mapping)]
    pods = [item for item in workload.get("pods", ()) if isinstance(item, Mapping)]
    if korean:
        lines = [
            f"Kubernetes API에서 Deployment {len(deployments)}개와 "
            f"Pod {len(pods)}개를 확인했습니다."
        ]
    else:
        lines = [f"Kubernetes API reported {len(deployments)} Deployments and {len(pods)} Pods."]
    lines.extend(
        f"- Deployment {item.get('namespace')}/{item.get('name')}: "
        f"ready {item.get('ready', 0)}/{item.get('desired', 0)}, "
        f"available {item.get('available', 0)}"
        for item in deployments
    )
    lines.extend(
        f"- Pod {item.get('namespace')}/{item.get('name')}: {item.get('phase', 'Unknown')}, "
        f"ready {item.get('ready', 0)}/{item.get('containers', 0)}"
        for item in pods
    )
    observed_at = workload.get("observed_at")
    source = workload.get("source")
    if source or observed_at:
        prefix = "Workload 근거" if korean else "Workload evidence"
        lines.append(f"{prefix}: {source or 'unknown'} at {observed_at or 'unknown time'}.")
    return lines


def _partial_workload_gap(
    result: Mapping[str, Any],
    workload: Mapping[str, Any],
    *,
    korean: bool,
) -> str:
    cluster_name = str(workload.get("cluster_name") or "unknown")
    uncovered = int(result.get("uncovered_cluster_count") or 0)
    if uncovered:
        if korean:
            return (
                f"이 workload 근거는 {cluster_name}만 포함합니다. "
                f"다른 AKS 클러스터 {uncovered}개는 "
                "Deployment와 Pod 근거가 없어 전체 배포 상태를 확정할 수 없습니다."
            )
        return (
            f"This workload evidence covers only {cluster_name}. {uncovered} other matched AKS "
            "clusters lack Deployment and Pod evidence, so overall deployment state is unconfirmed."
        )
    if korean:
        return "Workload 응답이 잘렸으므로 전체 Deployment와 Pod 상태를 확정할 수 없습니다."
    return (
        "The workload response is truncated, so complete Deployment and Pod state is unconfirmed."
    )


def inventory_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
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
        "provider_type": _optional_text(props.get("providerType")),
        "name": name,
        "status": str(raw.get("status") or "unknown"),
        "location": _optional_text(props.get("location") or raw.get("location")),
        "resource_group": _optional_text(props.get("resourceGroup") or raw.get("resource_group")),
    }


def _safe_link(raw: Mapping[str, Any], id_to_name: Mapping[str, str]) -> dict[str, str] | None:
    source = id_to_name.get(str(raw.get("source")))
    target = id_to_name.get(str(raw.get("target")))
    link_type = raw.get("type")
    if source is None or target is None or not isinstance(link_type, str):
        return None
    return {"source": source, "target": target, "type": link_type}


def _predicate_values(query: InventoryQuery, field: InventoryField) -> tuple[str, ...]:
    predicate = next((item for item in query.predicates if item.field is field), None)
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


def _resource_line(resource: Mapping[str, Any], *, korean: bool) -> str:
    details = [str(resource.get("type")), str(resource.get("status"))]
    if resource.get("location"):
        details.append(str(resource["location"]))
    if resource.get("resource_group"):
        details.append(f"resource group {resource['resource_group']}")
    prefix = "리소스" if korean else "Resource"
    return f"- {prefix} {resource.get('name')}: " + ", ".join(details)


__all__ = [
    "InventoryChatTools",
    "InventoryActivityProvider",
    "KubernetesWorkloadProvider",
    "inventory_evidence_refs",
    "inventory_execution_query",
    "needs_inventory_evidence",
    "partial_inventory_findings_are_grounded",
    "render_inventory_answer",
]
