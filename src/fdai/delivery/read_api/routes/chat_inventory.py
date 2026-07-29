"""Deterministic Azure inventory evidence and answers for Command Deck."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver
from fdai.delivery.read_api.routes.inventory_graph import InventoryGraphProvider

_RESOURCE_INTENT: Final = re.compile(
    r"\b(?:azure\s+)?(?:resources?|assets?|inventory|virtual machines?|storage accounts?|"
    r"databases?|dbs?|postgres(?:ql)?|sql databases?|kubernetes clusters?|vnets?|"
    r"virtual networks?|managed identit(?:y|ies)|key vaults?|resource groups?|public ips?|"
    r"nsgs?)\b"
    r"|(?<![A-Za-z0-9_])(?:aks|vms?)(?![A-Za-z0-9_])"
    r"|Azure\s*리소스|인벤토리|가상\s*머신|스토리지\s*계정|데이터베이스|"
    r"쿠버네티스|클러스터|가상\s*네트워크|관리형\s*ID|키\s*볼트|리소스\s*그룹|"
    r"공인\s*IP|네트워크\s*보안\s*그룹",
    re.IGNORECASE,
)
_QUESTION_INTENT: Final = re.compile(
    r"\b(?:how many|count|list|show|which|what|where|find|named|location|status|"
    r"group|types?|summary|exist|depend|attach|connect)\b|\?"
    r"|몇\s*개|개수|목록|보여|어떤|어디|찾아|이름|위치|상태|그룹|종류|유형|"
    r"의존|연결|붙어|뭐|있어",
    re.IGNORECASE,
)
_MUTATION_INTENT: Final = re.compile(
    r"\b(?:create|delete|drop|restart|scale|restore|update)\b"
    r"|생성|삭제|재시작|스케일|복구|수정",
    re.IGNORECASE,
)
_DIAGNOSIS_INTENT: Final = re.compile(
    r"\b(?:why|cause|latency|slow)\b|왜|원인|지연|느려",
    re.IGNORECASE,
)
_NON_INVENTORY_METRIC_INTENT: Final = re.compile(
    r"\b(?:cpu|memory|latency|throughput|usage|utilization|eps)\b"
    r"|메트릭|사용률|이용률|처리량|지연",
    re.IGNORECASE,
)
_IMPACT_SCOPE_INTENT: Final = re.compile(
    r"\b(?:affected|impact(?:ed)?|blast\s+radius)\b|영향|영향\s*범위",
    re.IGNORECASE,
)
_COUNT_INTENT: Final = re.compile(r"\b(?:how many|count)\b|몇\s*개|개수", re.IGNORECASE)
_TYPE_SUMMARY_INTENT: Final = re.compile(
    r"\b(?:resource types?|types? exist|inventory summary)\b|"
    r"리소스\s*(?:종류|유형)|인벤토리\s*요약",
    re.IGNORECASE,
)
_RELATIONSHIP_INTENT: Final = re.compile(
    r"\b(?:depend|dependency|attached|connected|relationship)\b|의존|연결|붙어|관계",
    re.IGNORECASE,
)
_LOCATION_INTENT: Final = re.compile(r"\b(?:where|location|region)\b|어디|위치|리전", re.IGNORECASE)
_STATUS_INTENT: Final = re.compile(
    r"\b(?:status|stopped|deallocated|running)\b|상태|중지|정지|실행\s*중|가동\s*중",
    re.IGNORECASE,
)
_WORKLOAD_INTENT: Final = re.compile(
    r"\b(?:deploy(?:ed|ing|ments?)?|pods?|workloads?|running apps?)\b"
    r"|배포|파드|워크로드|실행\s*중인\s*앱",
    re.IGNORECASE,
)
_GROUP_FILTER: Final = re.compile(
    r"(?:resource\s*group|리소스\s*그룹)(?:\s*(?:named|이름(?:이|은)?))?\s*[:=]?\s*([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_NAME_FILTER: Final = re.compile(
    r"(?:named|name(?:d)?|이름(?:이|은)?)\s*[:=]?\s*([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)

_TYPE_ALIASES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("compute.vm", ("virtual machine", "virtual machines", " vm ", "vms", "가상 머신")),
    ("object-storage", ("storage account", "storage accounts", "스토리지 계정")),
    ("postgresql-server", ("postgres", "postgresql", "postgres server", " db ")),
    ("sql-database", ("sql database", "sql databases", "데이터베이스", " db ")),
    ("kubernetes-cluster", ("aks", "kubernetes cluster", "쿠버네티스", "클러스터")),
    ("network.vnet", ("vnet", "virtual network", "virtual networks", "가상 네트워크")),
    ("managed-identity", ("managed identity", "managed identities", "관리형 id")),
    ("secret-store", ("key vault", "key vaults", "키 볼트")),
    ("resource-group", ("resource group", "resource groups", "리소스 그룹")),
    ("network.public-ip", ("public ip", "public ips", "공인 ip")),
    ("network.nsg", ("nsg", "nsgs", "network security group", "네트워크 보안 그룹")),
)
_STATUS_FILTERS: Final[tuple[tuple[re.Pattern[str], tuple[str, ...]], ...]] = (
    (
        re.compile(r"\b(?:stopped|deallocated)\b|중지|정지", re.IGNORECASE),
        ("stopped", "deallocated"),
    ),
    (re.compile(r"\brunning\b|실행\s*중|가동\s*중", re.IGNORECASE), ("running",)),
)
_MAX_RESOURCES = 40
_MAX_LINKS = 40
KubernetesWorkloadProvider = Callable[[], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class InventoryChatTools:
    """Resolve Azure resource questions from the authoritative graph provider."""

    provider: InventoryGraphProvider
    fallback: ChatToolResolver | None = None
    workload_provider: KubernetesWorkloadProvider | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if not needs_inventory_evidence(prompt):
            return await self._fallback(prompt, principal_id=principal_id)
        try:
            graph = dict(await self.provider(None, 4, ("contains", "attached_to", "depends_on")))
            result = _project_inventory_result(prompt, graph)
            if result.get("coverage_gap") == "kubernetes_workloads":
                result = await self._resolve_workloads(result)
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_inventory",
            "authority": "server_inventory_graph",
            "result": result,
        }

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

    return bool(
        not _MUTATION_INTENT.search(prompt)
        and not _DIAGNOSIS_INTENT.search(prompt)
        and not _NON_INVENTORY_METRIC_INTENT.search(prompt)
        and not _IMPACT_SCOPE_INTENT.search(prompt)
        and _RESOURCE_INTENT.search(prompt)
        and _QUESTION_INTENT.search(prompt)
    )


def _project_inventory_result(prompt: str, graph: Mapping[str, Any]) -> dict[str, Any]:
    raw_resources = graph.get("resources")
    raw_links = graph.get("links")
    if not isinstance(raw_resources, (list, tuple)) or not isinstance(raw_links, (list, tuple)):
        return {"status": "unavailable", "reason": "invalid_inventory_payload"}

    resources: list[dict[str, Any]] = []
    for raw_resource in raw_resources:
        if not isinstance(raw_resource, Mapping):
            continue
        resource = _safe_resource(raw_resource)
        if resource is not None:
            resources.append(resource)
    id_to_name = {str(item["id"]): str(item["name"]) for item in resources}
    managed = [item for item in resources if item["type"] != "subscription"]
    group_filter = _capture(_GROUP_FILTER, prompt)
    requested_types = _requested_types(prompt)
    status_filter = _requested_statuses(prompt)
    if (
        group_filter
        and "resource-group" in requested_types
        and re.search(
            r"\b(?:azure\s+)?resources?\b|Azure\s*리소스",
            prompt,
            re.IGNORECASE,
        )
    ):
        requested_types = tuple(item for item in requested_types if item != "resource-group")
    name_filter = _capture(_NAME_FILTER, prompt)
    matched = [
        item
        for item in managed
        if (not requested_types or item["type"] in requested_types)
        and (
            not status_filter
            or any(state in str(item["status"]).casefold() for state in status_filter)
        )
        and (
            not group_filter
            or str(item.get("resource_group", "")).casefold() == group_filter.casefold()
        )
        and (not name_filter or name_filter.casefold() in str(item["name"]).casefold())
    ]
    links = [
        projected
        for item in raw_links
        if isinstance(item, Mapping) and (projected := _safe_link(item, id_to_name)) is not None
    ]
    if _RELATIONSHIP_INTENT.search(prompt) and matched:
        names = {str(item["name"]) for item in matched}
        links = [item for item in links if item["source"] in names or item["target"] in names]

    workload_query = bool(
        _WORKLOAD_INTENT.search(prompt) and "kubernetes-cluster" in requested_types
    )
    return {
        "status": "partial" if workload_query else "matched",
        "query_kind": _query_kind(prompt),
        "requested_types": list(requested_types),
        "status_filter": list(status_filter),
        "resource_group": group_filter,
        "name_filter": name_filter,
        "snapshot_at": _optional_text(graph.get("snapshot_at")),
        "freshness": _optional_text(graph.get("freshness")),
        "source": _optional_text(graph.get("source")),
        "active_view": _optional_text(graph.get("active_view")) or "provider-default",
        "truncated": bool(graph.get("truncated")),
        "total_resources": len(managed),
        "matched_count": len(matched),
        "type_counts": dict(sorted(Counter(str(item["type"]) for item in managed).items())),
        "resources": [
            {key: value for key, value in item.items() if key != "id"}
            for item in matched[:_MAX_RESOURCES]
        ],
        "links": links[:_MAX_LINKS] if _RELATIONSHIP_INTENT.search(prompt) else [],
        "coverage_gap": "kubernetes_workloads" if workload_query else None,
    }


def render_inventory_answer(evidence: Mapping[str, Any], *, locale: str | None) -> str | None:
    """Render one inventory tool result without model inference."""

    if evidence.get("tool") != "query_inventory":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
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

    if korean:
        lines = [
            f"현재 Azure inventory view '{active_view}'의 {total}개 중 "
            f"질문과 일치하는 리소스는 {count}개입니다."
        ]
        lines.extend(_answer_detail_lines(result, resources, korean=True))
        if result.get("status") == "partial":
            workload = result.get("workload")
            if isinstance(workload, Mapping):
                lines.append(_partial_workload_gap(result, workload, korean=True))
            else:
                lines.append(
                    "이 Azure inventory 근거는 AKS 클러스터 리소스 상태까지만 포함하며, "
                    "클러스터 내부 Deployment와 Pod는 포함하지 않습니다. 따라서 앱 배포 여부는 "
                    "Kubernetes workload 근거가 연결되기 전에는 확정할 수 없습니다."
                )
        lines.append(f"근거: {source}, snapshot {snapshot}, freshness {freshness}.")
        if truncated:
            lines.append("인벤토리 snapshot이 잘렸으므로 실제 리소스 수가 더 많을 수 있습니다.")
        return "\n".join(lines)

    lines = [
        f"{count} of {total} resources in Azure inventory view '{active_view}' match the question."
    ]
    lines.extend(_answer_detail_lines(result, resources, korean=False))
    if result.get("status") == "partial":
        workload = result.get("workload")
        if isinstance(workload, Mapping):
            lines.append(_partial_workload_gap(result, workload, korean=False))
        else:
            lines.append(
                "This Azure inventory evidence covers AKS cluster resources only; it does not "
                "include in-cluster Deployments or Pods. Application deployment cannot be "
                "confirmed until Kubernetes workload evidence is connected."
            )
    lines.append(f"Evidence: {source}, snapshot {snapshot}, freshness {freshness}.")
    if truncated:
        lines.append("The inventory snapshot is truncated, so additional resources may exist.")
    return "\n".join(lines)


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
    if query_kind == "types":
        counts = result.get("type_counts", {})
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
    return [_resource_line(item, korean=korean) for item in resources]


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
    refs = [f"inventory:{source}@{snapshot}"] if source and snapshot else []
    workload = result.get("workload")
    if isinstance(workload, Mapping):
        workload_source = workload.get("source")
        observed_at = workload.get("observed_at")
        if workload_source and observed_at:
            refs.append(f"kubernetes:{workload_source}@{observed_at}")
    return tuple(refs)


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


def _requested_types(prompt: str) -> tuple[str, ...]:
    lowered = f" {prompt.casefold()} "
    return tuple(
        resource_type
        for resource_type, aliases in _TYPE_ALIASES
        if any(alias in lowered for alias in aliases)
    )


def _requested_statuses(prompt: str) -> tuple[str, ...]:
    return tuple(
        state for pattern, states in _STATUS_FILTERS if pattern.search(prompt) for state in states
    )


def _query_kind(prompt: str) -> str:
    if _TYPE_SUMMARY_INTENT.search(prompt):
        return "types"
    if _RELATIONSHIP_INTENT.search(prompt):
        return "relationships"
    if _COUNT_INTENT.search(prompt):
        return "count"
    if _LOCATION_INTENT.search(prompt):
        return "location"
    if _STATUS_INTENT.search(prompt):
        return "status"
    return "list"


def _capture(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    return match.group(1) if match else None


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
    "KubernetesWorkloadProvider",
    "inventory_evidence_refs",
    "needs_inventory_evidence",
    "render_inventory_answer",
]
