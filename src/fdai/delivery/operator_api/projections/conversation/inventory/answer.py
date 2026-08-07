"""Render verified inventory evidence into deterministic conversation answers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryQueryKind,
    InventoryQuerySource,
)
from fdai.delivery.operator_api.projections.conversation.inventory.activity import (
    render_inventory_activity,
)
from fdai.delivery.operator_api.projections.conversation.inventory.rendering import (
    _answer_detail_lines,
    _inventory_evidence_line,
    _partial_workload_gap,
    _render_inventory_chart_answer,
    _render_inventory_semantic_clarification,
    _render_inventory_table_answer,
    _safe_count_mapping,
)
from fdai.delivery.operator_api.projections.conversation.inventory.schedule import (
    render_scheduled_shutdown_answer,
)


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
    if result.get("query_kind") == InventoryQueryKind.SCHEDULED_SHUTDOWN.value:
        return render_scheduled_shutdown_answer(result, korean=korean)
    if (
        result.get("status") == "clarification"
        and result.get("reason") == "inventory_semantic_confirmation_required"
    ):
        return _render_inventory_semantic_clarification(result, korean=korean)
    if result.get("reason") == "inventory_semantic_interpretation_required":
        return (
            "요청의 상태 또는 작업 의미를 확정할 수 없어 Azure inventory를 조회하지 않았습니다."
            if korean
            else (
                "The request's state or operation meaning could not be confirmed, so Azure "
                "inventory was not queried."
            )
        )
    if result.get("status") not in {"matched", "partial"}:
        if result.get("reason") == "topology_selector_required":
            return (
                "Topology 조회에는 정확한 source와 target resource name 또는 선택된 network "
                "resource가 필요합니다. 대상을 지정한 뒤 다시 시도하세요."
                if korean
                else (
                    "Topology queries require exact source and target resource names or a "
                    "selected network resource. Specify the resources and try again."
                )
            )
        if result.get("reason") == "active_view_resource_group_unavailable":
            return (
                "현재 Architecture 화면에서 선택된 리소스 그룹을 확인할 수 없습니다. "
                "리소스 그룹을 선택하거나 이름을 지정한 뒤 다시 시도하세요."
                if korean
                else "No resource group is selected on the current Architecture screen. "
                "Select a resource group or specify its name, then try again."
            )
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
    state_coverage = bool(result.get("state_coverage"))
    inventory_coverage = bool(result.get("inventory_coverage"))
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

    if state_coverage:
        unavailable_counts = _safe_count_mapping(result.get("state_unavailable_type_counts"))
        available_counts = _safe_count_mapping(result.get("state_available_type_counts"))
        unavailable_resources = int(result.get("state_unavailable_resource_count") or 0)
        if korean:
            lines = [
                f"선택 범위의 provider-native 리소스 {count}개를 확인했습니다. "
                f"운영 상태를 직접 확인할 수 없는 리소스는 {unavailable_resources}개이며, "
                f"{len(unavailable_counts)}개 유형입니다.",
                "**운영 상태 직접 확인 가능 유형**",
            ]
            lines.extend(f"- {kind}: {value}개" for kind, value in available_counts.items())
            lines.append("**운영 상태 직접 확인 불가 유형**")
            lines.extend(f"- {kind}: {value}개" for kind, value in unavailable_counts.items())
        else:
            lines = [
                f"Checked {count} provider-native resources. {unavailable_resources} resources "
                f"across {len(unavailable_counts)} types lack a directly observed "
                "operational state.",
                "**Types with directly observed operational state**",
            ]
            lines.extend(f"- {kind}: {value}" for kind, value in available_counts.items())
            lines.append("**Types without directly observed operational state**")
            lines.extend(f"- {kind}: {value}" for kind, value in unavailable_counts.items())
        lines.append(_inventory_evidence_line(source, snapshot, freshness, korean=korean))
        if truncated:
            lines.append(
                "인벤토리 snapshot이 잘렸으므로 coverage가 부분적입니다."
                if korean
                else "The inventory snapshot is truncated, so coverage is partial."
            )
        return "\n".join(lines)

    if inventory_coverage:
        checked_counts = _safe_count_mapping(result.get("inventory_checked_type_counts"))
        complete = bool(result.get("inventory_coverage_complete"))
        failed_types = int(result.get("inventory_failed_type_count") or 0)
        unavailable_counts = _safe_count_mapping(result.get("state_unavailable_type_counts"))
        if korean:
            lines = [
                f"Provider inventory에서 리소스 {count}개, 유형 {len(checked_counts)}개를 "
                "확인했습니다.",
                "**확인한 유형**",
            ]
            lines.extend(f"- {kind}: {value}개" for kind, value in checked_counts.items())
            lines.extend(
                (
                    "**건너뛴 유형**: 없음",
                    f"**읽기 실패 유형**: {failed_types}개",
                    f"운영 상태 직접 확인 불가: {len(unavailable_counts)}개 유형. "
                    "이는 inventory 읽기 실패가 아닙니다.",
                )
                if complete
                else (
                    "**건너뛴 유형**: snapshot truncation으로 확정 불가",
                    f"**읽기 실패 유형**: {failed_types}개",
                )
            )
        else:
            lines = [
                f"Checked {count} provider inventory resources across {len(checked_counts)} types.",
                "**Checked types**",
            ]
            lines.extend(f"- {kind}: {value}" for kind, value in checked_counts.items())
            lines.extend(
                (
                    "**Skipped types**: none",
                    f"**Failed-to-read types**: {failed_types}",
                    f"Operational state unavailable for {len(unavailable_counts)} types; "
                    "this is not an inventory read failure.",
                )
                if complete
                else (
                    "**Skipped types**: unknown because the snapshot is truncated",
                    f"**Failed-to-read types**: {failed_types}",
                )
            )
        lines.append(_inventory_evidence_line(source, snapshot, freshness, korean=korean))
        return "\n".join(lines)

    if answer_format == "table":
        return _render_inventory_table_answer(
            resources,
            requested_types=(
                tuple(str(item) for item in result.get("requested_types", []))
                if isinstance(result.get("requested_types"), list)
                else ()
            ),
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


__all__ = ["render_inventory_answer"]
