"""Render deterministic inventory answer details and execution queries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.routes.chat_inventory_projection import _optional_text
from fdai.delivery.operator_api.routes.chat_inventory_query import (
    InventoryQuery,
    normalize_inventory_value,
)

_MAX_RESOURCES = 40


def _render_inventory_semantic_clarification(
    result: Mapping[str, Any],
    *,
    korean: bool,
) -> str:
    raw_candidates = result.get("semantic_candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    labels: list[str] = []
    locale = "ko" if korean else "en"
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_labels = candidate.get("labels")
        label = candidate_labels.get(locale) if isinstance(candidate_labels, Mapping) else None
        kind = str(candidate.get("kind") or "state")
        kind_label = (
            ("현재 상태" if kind == "state" else "작업 이력")
            if korean
            else ("Current state" if kind == "state" else "Operation history")
        )
        labels.append(f"{kind_label}: {label or candidate.get('concept_id') or 'unknown'}")
    bounded_labels = tuple(dict.fromkeys(labels))[:3]
    options = (
        ", ".join(bounded_labels)
        if bounded_labels
        else ("상태 의미" if korean else "state meaning")
    )
    if korean:
        return (
            f"요청의 의미를 확정해야 합니다. 다음 중 하나를 지정해 주세요: {options}. "
            "확정 전에는 Azure inventory를 조회하지 않았습니다."
        )
    return (
        f"The request needs semantic confirmation. Specify one of: {options}. "
        "Azure inventory was not queried before confirmation."
    )


def inventory_screen_scope_unavailable_evidence(
    scope_context: object,
) -> dict[str, Any] | None:
    """Return a typed hold when active-view inventory scope has no trusted selector."""

    if not isinstance(scope_context, Mapping) or scope_context.get("status") != "unavailable":
        return None
    return {
        "tool": "query_inventory",
        "authority": "server_inventory_graph",
        "result": {
            "status": "unavailable",
            "reason": "active_view_resource_group_unavailable",
        },
    }


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
        "query_language": "IQL",
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
    requested_types: tuple[str, ...],
    korean: bool,
    count: int,
    total: int,
    active_view: str,
    source: str,
    snapshot: str,
    freshness: str,
    truncated: bool,
) -> str:
    resource_group_table = (
        requested_types == ("resource-group",)
        or bool(resources)
        and all(item.get("type") == "resource-group" for item in resources)
    )
    table_headers: tuple[str, ...]
    table_fields: tuple[str, ...]
    if resource_group_table:
        lead = (
            f"구독 범위에서 리소스 그룹 {count}개를 확인했습니다."
            if korean
            else f"Found {count} resource groups in the subscription scope."
        )
        table_headers = (
            ("리소스 그룹", "위치", "상태") if korean else ("Resource group", "Location", "Status")
        )
        table_fields = ("name", "location", "status")
    else:
        lead = (
            f"현재 Azure inventory view '{active_view}'의 {total}개 중 {count}개가 일치합니다."
            if korean
            else f"{count} of {total} resources in Azure inventory view '{active_view}' match."
        )
        table_headers = (
            ("이름", "형식", "상태", "위치", "리소스 그룹")
            if korean
            else ("Name", "Type", "Status", "Location", "Resource group")
        )
        table_fields = ("name", "type", "status", "location", "resource_group")
    lines = [
        lead,
        "",
        "| " + " | ".join(table_headers) + " |",
        "| " + " | ".join("---" for _ in table_headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_markdown_cell(item.get(field) or "-") for field in table_fields) + " |"
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


def _safe_count_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): count
        for key, count in value.items()
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0
    }


def _resource_line(resource: Mapping[str, Any], *, korean: bool) -> str:
    details = [str(resource.get("type")), str(resource.get("status"))]
    if resource.get("location"):
        details.append(str(resource["location"]))
    if resource.get("resource_group"):
        details.append(f"resource group {resource['resource_group']}")
    prefix = "리소스" if korean else "Resource"
    return f"- {prefix} {resource.get('name')}: " + ", ".join(details)
