"""Deterministic Azure inventory evidence and answers for Command Deck."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver
from fdai.delivery.read_api.routes.inventory_graph import InventoryGraphProvider

_RESOURCE_INTENT: Final = re.compile(
    r"\b(?:azure\s+)?(?:resources?|inventory|virtual machines?|vms?|storage accounts?|"
    r"databases?|postgres(?:ql)?|sql databases?|aks|kubernetes clusters?|vnets?|"
    r"virtual networks?|managed identities|key vaults?|resource groups?|public ips?|nsgs?)\b"
    r"|Azure\s*리소스|인벤토리|가상\s*머신|스토리지\s*계정|데이터베이스|"
    r"쿠버네티스|클러스터|가상\s*네트워크|관리형\s*ID|키\s*볼트|리소스\s*그룹|"
    r"공인\s*IP|네트워크\s*보안\s*그룹",
    re.IGNORECASE,
)
_QUESTION_INTENT: Final = re.compile(
    r"\b(?:how many|count|list|show|which|what|where|find|named|location|status|"
    r"group|types?|depend|attach|connect)\b"
    r"|몇\s*개|개수|목록|보여|어떤|어디|찾아|이름|위치|상태|그룹|종류|유형|"
    r"의존|연결|붙어",
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
_STATUS_INTENT: Final = re.compile(r"\bstatus\b|상태", re.IGNORECASE)
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
    ("postgresql-server", ("postgres", "postgresql", "postgres server")),
    ("sql-database", ("sql database", "sql databases", "데이터베이스")),
    ("kubernetes-cluster", ("aks", "kubernetes cluster", "쿠버네티스", "클러스터")),
    ("network.vnet", ("vnet", "virtual network", "virtual networks", "가상 네트워크")),
    ("managed-identity", ("managed identity", "managed identities", "관리형 id")),
    ("secret-store", ("key vault", "key vaults", "키 볼트")),
    ("resource-group", ("resource group", "resource groups", "리소스 그룹")),
    ("network.public-ip", ("public ip", "public ips", "공인 ip")),
    ("network.nsg", ("nsg", "nsgs", "network security group", "네트워크 보안 그룹")),
)
_MAX_RESOURCES = 40
_MAX_LINKS = 40


@dataclass(frozen=True, slots=True)
class InventoryChatTools:
    """Resolve Azure resource questions from the authoritative graph provider."""

    provider: InventoryGraphProvider
    fallback: ChatToolResolver | None = None

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
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_inventory",
            "authority": "server_inventory_graph",
            "result": result,
        }

    async def _fallback(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if self.fallback is None:
            return None
        return await self.fallback.resolve(prompt, principal_id=principal_id)


def needs_inventory_evidence(prompt: str) -> bool:
    """Return whether a question asks for observed Azure resource inventory."""

    return bool(_RESOURCE_INTENT.search(prompt) and _QUESTION_INTENT.search(prompt))


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

    return {
        "status": "matched",
        "query_kind": _query_kind(prompt),
        "requested_types": list(requested_types),
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
    }


def render_inventory_answer(evidence: Mapping[str, Any], *, locale: str | None) -> str | None:
    """Render one inventory tool result without model inference."""

    if evidence.get("tool") != "query_inventory":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if result.get("status") != "matched":
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
        lines.append(f"근거: {source}, snapshot {snapshot}, freshness {freshness}.")
        if truncated:
            lines.append("인벤토리 snapshot이 잘렸으므로 실제 리소스 수가 더 많을 수 있습니다.")
        return "\n".join(lines)

    lines = [
        f"{count} of {total} resources in Azure inventory view '{active_view}' match the question."
    ]
    lines.extend(_answer_detail_lines(result, resources, korean=False))
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


def inventory_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    source = result.get("source")
    snapshot = result.get("snapshot_at")
    return (f"inventory:{source}@{snapshot}",) if source and snapshot else ()


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
    "inventory_evidence_refs",
    "needs_inventory_evidence",
    "render_inventory_answer",
]
