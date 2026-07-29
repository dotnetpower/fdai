"""Deterministic natural-language compiler for verified inventory queries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from fdai.delivery.read_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    InventoryQueryKind,
    InventoryQuerySource,
    normalize_inventory_value,
)

_RESOURCE_SUBJECT: Final = re.compile(
    r"\b(?:azure\s+)?(?:resources?|assets?|inventory|virtual machines?|vms?|"
    r"storage accounts?|databases?|dbs?|postgres(?:ql)?|sql databases?|"
    r"kubernetes clusters?|vnets?|"
    r"virtual networks?|managed identit(?:y|ies)|key vaults?|resource groups?|public ips?|"
    r"nsgs?)\b|Azure\s*리소스|인벤토리|가상\s*머신|스토리지\s*계정|데이터베이스|"
    r"쿠버네티스|클러스터|가상\s*네트워크|관리형\s*ID|키\s*볼트|리소스\s*그룹|"
    r"공인\s*IP|네트워크\s*보안\s*그룹|리소스",
    re.IGNORECASE,
)
_RESOURCE_TOKEN: Final = re.compile(
    r"(?<![A-Za-z0-9_])(?:aks|vms?)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_READ_MARKER: Final = re.compile(
    r"\b(?:how many|count|list|show|which|what|where|find|status|types?|summary|exist|"
    r"recent|last|changed|created|deleted|started|stopped|updated)\b|\?|"
    r"몇\s*개|개수|목록|보여|어떤|어디|찾아|상태|종류|유형|있어|최근|지난|"
    r"변경된|생성된|삭제된|시작된|중지된|수정된",
    re.IGNORECASE,
)
_MUTATION_REQUEST: Final = re.compile(
    r"^\s*(?:please\s+)?(?:create|delete|drop|restart|scale|restore|update|start|stop)\b|"
    r"(?:생성|삭제|재시작|스케일|복구|수정|시작|중지).{0,12}"
    r"(?:해줘|해주세요|하자|시켜|적용해|실행해)",
    re.IGNORECASE,
)
_DIAGNOSIS_OR_METRIC: Final = re.compile(
    r"\b(?:why|cause|latency|slow|cpu|memory|throughput|usage|utilization|eps)\b|"
    r"\b(?:affected|impact(?:ed)?|blast\s+radius)\b|"
    r"왜|원인|지연|느려|메트릭|사용률|이용률|처리량|영향|영향\s*범위",
    re.IGNORECASE,
)
_ACTIVITY_EXPLICIT: Final = re.compile(
    r"\b(?:changed|created|deleted|updated)\s+(?:azure\s+)?(?:resources?|assets?)\b|"
    r"\b(?:resources?|assets?)\s+(?:changed|created|deleted|updated)\b|"
    r"(?:변경된|생성된|삭제된|수정된)\s*(?:Azure\s*)?리소스",
    re.IGNORECASE,
)
_ACTIVITY_TEMPORAL: Final = re.compile(
    r"\b(?:recent|recently|last|past|history)\b|최근|지난|이력|언제|누가",
    re.IGNORECASE,
)
_ACTIVITY_OPERATION: Final = re.compile(
    r"\b(?:started|stopped|changed|created|deleted|updated)\b|"
    r"시작된|중지된|변경된|생성된|삭제된|수정된",
    re.IGNORECASE,
)
_COUNT: Final = re.compile(r"\b(?:how many|count)\b|몇\s*개|개수", re.IGNORECASE)
_TYPES: Final = re.compile(
    r"\b(?:resource types?|types? exist|inventory summary)\b|"
    r"리소스\s*(?:종류|유형)|인벤토리\s*요약",
    re.IGNORECASE,
)
_RELATIONSHIPS: Final = re.compile(
    r"\b(?:depend|dependency|attached|connected|relationship)\b|의존|연결|붙어|관계",
    re.IGNORECASE,
)
_GROUP_FILTER: Final = re.compile(
    r"(?:resource\s*group|리소스\s*그룹)(?:\s*(?:named|이름(?:이|은)?))?"
    r"\s*[:=]?\s*([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_NAME_FILTER: Final = re.compile(
    r"(?:named|name(?:d)?|이름(?:이|은)?)\s*[:=]?\s*([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_ENGLISH_WINDOW: Final = re.compile(
    r"\b(?:last|past)\s+([1-9][0-9]{0,2})\s*(hours?|days?|weeks?)\b",
    re.IGNORECASE,
)
_KOREAN_WINDOW: Final = re.compile(r"(?:최근|지난)\s*([1-9][0-9]{0,2})\s*(시간|일|주)")
_PREFIX_FILTER: Final = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9_.-]{1,63}|[가-힣]{2,20})\s*"
    r"(?:된|중인)?\s*(?:Azure\s*)?(?:resources?|assets?|리소스)\b",
    re.IGNORECASE,
)
_LOCATION_FILTER: Final = re.compile(
    r"\b(?:resources?|assets?)\s+(?:in|at)\s+([A-Za-z0-9_.-]+)\b|"
    r"([A-Za-z0-9_.-]+)(?:의|에|에서)\s*(?:Azure\s*)?리소스",
    re.IGNORECASE,
)
_COPULA_FILTER: Final = re.compile(
    r"\b(?:resources?|assets?)\s+(?:are|is)\s+([A-Za-z][A-Za-z0-9_.-]{1,63})\b",
    re.IGNORECASE,
)
_GENERIC_PREFIXES: Final = frozenset(
    {"all", "any", "azure", "current", "list", "show", "what", "which", "어떤", "전체"}
)

_TYPE_ALIASES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("compute.vm", ("virtual machine", "virtual machines", " vm ", " vms ", "가상 머신")),
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
_STATUS_ALIASES: Final[tuple[tuple[re.Pattern[str], frozenset[str]], ...]] = (
    (
        re.compile(r"\b(?:stopped|deallocated)\b|중지|정지", re.IGNORECASE),
        frozenset({"stopped", "deallocated"}),
    ),
    (
        re.compile(r"\brunning\b|실행\s*중|가동\s*중", re.IGNORECASE),
        frozenset({"running"}),
    ),
)
_OPERATION_ALIASES: Final[tuple[tuple[re.Pattern[str], tuple[str, ...]], ...]] = (
    (re.compile(r"\bstarted\b|시작된", re.IGNORECASE), ("start",)),
    (
        re.compile(r"\bstopped\b|중지된|정지된", re.IGNORECASE),
        ("stop", "deallocate", "power off"),
    ),
    (re.compile(r"\bdeleted\b|삭제된", re.IGNORECASE), ("delete",)),
    (
        re.compile(r"\b(?:changed|created|updated)\b|변경된|생성된|수정된", re.IGNORECASE),
        ("write",),
    ),
)
_DEFAULT_ACTIVITY_LOOKBACK_SECONDS = 7 * 24 * 3_600


def is_inventory_question(prompt: str) -> bool:
    """Return whether text is an observed resource read rather than a mutation or diagnosis."""

    return bool(
        prompt.strip()
        and not _MUTATION_REQUEST.search(prompt)
        and not _DIAGNOSIS_OR_METRIC.search(prompt)
        and (_RESOURCE_SUBJECT.search(prompt) or _RESOURCE_TOKEN.search(prompt))
        and _READ_MARKER.search(prompt)
    )


def compile_inventory_query(
    prompt: str,
    *,
    resources: Sequence[Mapping[str, Any]] = (),
) -> InventoryQuery | None:
    """Compile one high-confidence resource read into a verified typed query."""

    if not is_inventory_question(prompt):
        return None
    source = _source(prompt)
    predicates: list[InventoryPredicate] = []
    group = _capture(_GROUP_FILTER, prompt)
    resource_types = _resource_types(prompt, resources)
    if group:
        resource_types = tuple(item for item in resource_types if item != "resource-group")
    if resource_types:
        predicates.append(_in_or_eq(InventoryField.RESOURCE_TYPE, resource_types))
    if group:
        predicates.append(
            InventoryPredicate(InventoryField.RESOURCE_GROUP, InventoryOperator.EQ, group)
        )
    name = _capture(_NAME_FILTER, prompt)
    if name:
        predicates.append(InventoryPredicate(InventoryField.NAME, InventoryOperator.CONTAINS, name))

    if source is InventoryQuerySource.ACTIVITY:
        operations = _operation_values(prompt)
        if operations:
            predicates.append(_in_or_eq(InventoryField.OPERATION, operations))
        predicates.append(
            InventoryPredicate(InventoryField.EVENT_STATUS, InventoryOperator.EQ, "succeeded")
        )
        return InventoryQuery(
            source=source,
            kind=_kind(prompt, source),
            predicates=tuple(predicates),
            lookback_seconds=_lookback_seconds(prompt),
        )

    statuses = _status_values(prompt, resources)
    if statuses:
        predicates.append(_in_or_eq(InventoryField.STATUS, statuses))
    location = _facet_value(prompt, resources, "location")
    if location:
        predicates.append(
            InventoryPredicate(InventoryField.LOCATION, InventoryOperator.EQ, location)
        )
    if _has_unresolved_filter(
        prompt,
        resource_types=resource_types,
        statuses=statuses,
        location=location,
        group=group,
        name=name,
    ):
        return None
    return InventoryQuery(
        source=source,
        kind=_kind(prompt, source),
        predicates=tuple(predicates),
    )


def _source(prompt: str) -> InventoryQuerySource:
    if _ACTIVITY_EXPLICIT.search(prompt) or (
        _ACTIVITY_TEMPORAL.search(prompt) and _ACTIVITY_OPERATION.search(prompt)
    ):
        return InventoryQuerySource.ACTIVITY
    return InventoryQuerySource.CURRENT


def _kind(prompt: str, source: InventoryQuerySource) -> InventoryQueryKind:
    if _COUNT.search(prompt):
        return InventoryQueryKind.COUNT
    if _TYPES.search(prompt):
        return InventoryQueryKind.TYPES
    if source is InventoryQuerySource.CURRENT and _RELATIONSHIPS.search(prompt):
        return InventoryQueryKind.RELATIONSHIPS
    return InventoryQueryKind.LIST


def _resource_types(
    prompt: str,
    resources: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    normalized = f" {normalize_inventory_value(prompt)} "
    observed = {
        str(item.get("type"))
        for item in resources
        if isinstance(item.get("type"), str) and item.get("type")
    }
    matched = {
        resource_type
        for resource_type, aliases in _TYPE_ALIASES
        if any(normalize_inventory_value(alias) in normalized for alias in aliases)
    }
    matched.update(
        resource_type
        for resource_type in observed
        if _contains_phrase(normalized, normalize_inventory_value(resource_type))
    )
    return tuple(sorted(matched))


def _status_values(
    prompt: str,
    resources: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    normalized_prompt = f" {normalize_inventory_value(prompt)} "
    observed = {
        normalize_inventory_value(item["status"])
        for item in resources
        if item.get("status") not in (None, "")
    }
    matched = {status for status in observed if _contains_phrase(normalized_prompt, status)}
    for pattern, terminal_states in _STATUS_ALIASES:
        if pattern.search(prompt):
            matched.update(
                status for status in observed if status.rsplit(" ", 1)[-1] in terminal_states
            )
    return tuple(sorted(matched))


def _operation_values(prompt: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            operation
            for pattern, operations in _OPERATION_ALIASES
            if pattern.search(prompt)
            for operation in operations
        )
    )


def _lookback_seconds(prompt: str) -> int:
    match = _ENGLISH_WINDOW.search(prompt)
    if match is not None:
        value = int(match.group(1))
        unit = match.group(2).casefold()
        multiplier = (
            3_600 if unit.startswith("hour") else 86_400 if unit.startswith("day") else 604_800
        )
        return value * multiplier
    match = _KOREAN_WINDOW.search(prompt)
    if match is not None:
        value = int(match.group(1))
        multiplier = {"시간": 3_600, "일": 86_400, "주": 604_800}[match.group(2)]
        return value * multiplier
    return _DEFAULT_ACTIVITY_LOOKBACK_SECONDS


def _facet_value(
    prompt: str,
    resources: Sequence[Mapping[str, Any]],
    field: str,
) -> str | None:
    normalized_prompt = f" {normalize_inventory_value(prompt)} "
    values = sorted(
        {str(item[field]) for item in resources if item.get(field) not in (None, "")},
        key=len,
        reverse=True,
    )
    return next(
        (
            value
            for value in values
            if _contains_phrase(normalized_prompt, normalize_inventory_value(value))
        ),
        None,
    )


def _contains_phrase(normalized_prompt: str, normalized_value: str) -> bool:
    if not normalized_value:
        return False
    if f" {normalized_value} " in normalized_prompt:
        return True
    return bool(
        re.search(
            rf"(?<![a-z0-9_.-]){re.escape(normalized_value)}"
            r"(?=(?:은|는|이|가|의|에|에서)?(?:\s|[?!,.;:]|$))",
            normalized_prompt,
            re.IGNORECASE,
        )
    )


def _has_unresolved_filter(
    prompt: str,
    *,
    resource_types: Sequence[str],
    statuses: Sequence[str],
    location: str | None,
    group: str | None,
    name: str | None,
) -> bool:
    if resource_types or statuses or location or group or name:
        return False
    prefix = _PREFIX_FILTER.search(prompt)
    if prefix is not None:
        candidate = normalize_inventory_value(prefix.group(1))
        if candidate not in _GENERIC_PREFIXES:
            return True
    return _LOCATION_FILTER.search(prompt) is not None or _COPULA_FILTER.search(prompt) is not None


def _in_or_eq(field: InventoryField, values: Sequence[str]) -> InventoryPredicate:
    unique = tuple(dict.fromkeys(values))
    return InventoryPredicate(
        field,
        InventoryOperator.EQ if len(unique) == 1 else InventoryOperator.IN,
        unique[0] if len(unique) == 1 else unique,
    )


def _capture(pattern: re.Pattern[str], prompt: str) -> str | None:
    match = pattern.search(prompt)
    return match.group(1) if match is not None else None


__all__ = ["compile_inventory_query", "is_inventory_question"]
