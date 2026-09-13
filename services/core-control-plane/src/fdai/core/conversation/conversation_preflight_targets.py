"""Exact target, time, and subscription-scope checks for typed preflight."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

GENERIC_SUBSCRIPTION_SCOPE_FILTERS = frozenset(
    {"subscription", "the subscription", "current subscription", "구독", "현재 구독"}
)
_ONE_HOUR_EXPRESSIONS = frozenset(
    {
        "last hour",
        "past hour",
        "previous hour",
        "the last hour",
        "the past hour",
        "the previous hour",
        "지난 1시간",
        "지난 한 시간",
        "최근 1시간",
        "최근 한 시간",
    }
)
_GENERIC_OPERATIONAL_TARGETS = frozenset(
    {
        "api management",
        "api management service",
        "api",
        "apim",
        "apim gateway",
        "apim service",
        "application gateway",
        "appgw",
        "azure api management",
        "azure api management gateway",
        "azure api management service",
        "azure application gateway",
        "all",
        "backend",
        "backend instance",
        "backend service",
        "current",
        "database",
        "databases",
        "db",
        "deployment",
        "each",
        "every",
        "gateway",
        "gpt",
        "gpt deployment",
        "gpt model",
        "gpt resource",
        "gpt resources",
        "gpt service",
        "model",
        "my",
        "name",
        "our",
        "operational",
        "power",
        "resource",
        "resource group",
        "resources",
        "region",
        "location",
        "selected deployment",
        "selected gateway",
        "state",
        "status",
        "the",
        "this deployment",
        "this gateway",
        "your",
        "게이트웨이",
        "모델",
        "배포",
        "백엔드",
        "리소스",
        "리소스 그룹",
        "지역",
        "자원",
        "상태",
        "이름",
        "애플리케이션 게이트웨이",
    }
)
_GENERIC_OPERATIONAL_TARGET_PATTERN = re.compile(
    r"(?:(?:gpt\s*)?\d+(?:\.\d+)+(?:\s+(?:deployment|model|resource|service))?|"
    r"(?:http\s*)?[1-5]\d\d)"
)
_SUBSCRIPTION_NAME_PATTERN = r"[^\W_](?:[\w.-]{0,62}[\w])?"
_SUBSCRIPTION_NAME_AFTER = re.compile(
    rf"(?i)\bsubscription\s+(?:named\s+)?({_SUBSCRIPTION_NAME_PATTERN})(?!\w)"
)
_EXPLICIT_NAMED_SUBSCRIPTION = re.compile(
    rf"(?i)\bsubscription\s+named\s+{_SUBSCRIPTION_NAME_PATTERN}(?!\w)"
)
_SUBSCRIPTION_NAME_BEFORE_KOREAN = re.compile(
    r"(?i)(?<!\S)([^\s,.;:!?]{1,64})\s+구독(?:의|은|는|이|가|을|를)?"
)
_SUBSCRIPTION_NAME_ATTACHED_KOREAN = re.compile(
    r"(?i)(?<![\w.-])([^\W_][\w.-]{0,62})구독(?:의|은|는|이|가|을|를)?"
)
_SUBSCRIPTION_NAME_BEFORE = re.compile(
    rf"(?i)(?<![\w.-])(?:the\s+)?({_SUBSCRIPTION_NAME_PATTERN})\s+"
    r"subscription(?:의|은|는|이|가|을|를|도)?(?!\w)"
)
_SUMMARY_TARGET_AFTER_OF = re.compile(
    r"(?i)\b(?:state|status|health)\s+of\s+([A-Za-z][A-Za-z0-9_.-]*)"
)
_SUMMARY_TARGET_BEFORE_STATUS = re.compile(
    r"(?i)\b([A-Za-z][A-Za-z0-9_.-]*)\s+(?:state|status|health)\b"
)
_SUMMARY_TARGET_BEFORE_KOREAN_STATUS = re.compile(
    r"(?i)(?<!\S)([^\s,.;:!?]{1,128})\s*(?:의\s*)?(?:상태|헬스)"
)
_GENERIC_SUBSCRIPTION_WORDS = frozenset(
    {
        "azure",
        "authorized",
        "configured",
        "current",
        "details",
        "health",
        "identity",
        "information",
        "name",
        "our",
        "please",
        "scope",
        "service",
        "state",
        "status",
        "that",
        "the",
        "this",
        "your",
        "my",
        "그",
        "내",
        "우리",
        "무슨",
        "어느",
        "어떤",
        "이",
        "저",
        "현재",
        "해당",
        "상태",
        "서비스",
        "세부",
        "세부사항",
        "구성",
        "설정",
        "좀",
        "제",
        "지금",
        "다시",
        "빨리",
        "자세히",
        "이름",
        "정보",
        "리소스",
        "목록",
        "상세",
        "알려줘",
        "알려줄래",
        "보여줘",
        "보여줄래",
        "확인해줘",
        "확인",
        "조회해줘",
        "검색해줘",
        "설명해줘",
        "말해줘",
        "뭐야",
        "범위",
        "식별자",
        "요약",
        "현황",
        "있는",
    }
)
_KOREAN_SUBSCRIPTION_PARTICLES = ("의", "은", "는", "이", "가", "을", "를", "도")
_KOREAN_REQUEST_PREDICATE_ENDINGS = ("주세요", "드립니다", "습니까", "나요", "줄래")
_TARGET_PREFIXES = (
    "the ",
    "a ",
    "an ",
    "this ",
    "that ",
    "these ",
    "those ",
    "some ",
    "selected ",
    "current ",
    "our ",
    "my ",
    "your ",
    "their ",
    "its ",
    "해당 ",
    "이 ",
    "그 ",
    "저 ",
    "선택한 ",
    "현재 ",
    "우리 ",
    "내 ",
)


def operational_target_is_generic(value: str) -> bool:
    """Return whether source text names only a generic operational category."""

    normalized = " ".join(value.casefold().split()).strip(".,:;!?()[]{}")
    while normalized.startswith(_TARGET_PREFIXES):
        normalized = normalized.removeprefix(
            next(prefix for prefix in _TARGET_PREFIXES if normalized.startswith(prefix))
        )
    return normalized in _GENERIC_OPERATIONAL_TARGETS or (
        _GENERIC_OPERATIONAL_TARGET_PATTERN.fullmatch(normalized) is not None
    )


def operational_target_is_exact(value: str) -> bool:
    """Return whether a target is an exact token-like name or path identity."""

    return not any(character.isspace() for character in value) and not (
        operational_target_is_generic(value)
    )


def named_subscription_requested(utterance: str) -> bool:
    """Return whether the utterance asks for a non-generic subscription."""

    if _EXPLICIT_NAMED_SUBSCRIPTION.search(utterance) is not None:
        return True
    after_candidates = tuple(
        match.group(1) for match in _SUBSCRIPTION_NAME_AFTER.finditer(utterance)
    )
    candidates = (
        *(match.group(1) for match in _SUBSCRIPTION_NAME_BEFORE_KOREAN.finditer(utterance)),
        *(match.group(1) for match in _SUBSCRIPTION_NAME_ATTACHED_KOREAN.finditer(utterance)),
        *(match.group(1) for match in _SUBSCRIPTION_NAME_BEFORE.finditer(utterance)),
    )
    return any(
        not _subscription_candidate_is_generic(candidate)
        and not candidate.endswith(_KOREAN_REQUEST_PREDICATE_ENDINGS)
        for candidate in after_candidates
    ) or any(not _subscription_candidate_is_generic(candidate) for candidate in candidates)


def collection_summary_exact_target_requested(
    utterance: str,
    *,
    subject_constraints: tuple[str, ...],
    catalog_constraints: frozenset[str] = frozenset(),
) -> bool:
    """Return whether a collection summary would discard a source-grounded target."""

    if any(
        constraint.startswith(("Resource.id=", "Resource.name=", "Resource.display_name="))
        for constraint in subject_constraints
    ):
        return True
    candidates = {match.group(1) for match in _SUMMARY_TARGET_AFTER_OF.finditer(utterance)}
    candidates.update(match.group(1) for match in _SUMMARY_TARGET_BEFORE_STATUS.finditer(utterance))
    candidates.update(
        match.group(1) for match in _SUMMARY_TARGET_BEFORE_KOREAN_STATUS.finditer(utterance)
    )
    folded = str.casefold(utterance)
    candidates.update(
        constraint
        for constraint in subject_constraints
        if constraint != "Resource"
        if not any(character.isspace() for character in constraint)
        if constraint.casefold() not in catalog_constraints
        if folded.count(constraint.casefold()) == 1
    )
    return any(
        not _candidate_is_catalog_constraint(candidate, catalog_constraints)
        and not operational_target_is_generic(candidate)
        for candidate in candidates
    )


def _candidate_is_catalog_constraint(
    candidate: str,
    catalog_constraints: frozenset[str],
) -> bool:
    folded = candidate.casefold()
    return folded in catalog_constraints or any(
        term.endswith(f" {folded}") for term in catalog_constraints
    )


def resource_catalog_constraints(descriptors: tuple[dict[str, Any], ...]) -> frozenset[str]:
    """Return Resource type values and group ids that are collection scope, not identities."""

    resource = next(
        (
            descriptor
            for descriptor in descriptors
            if descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
        ),
        None,
    )
    properties = resource.get("properties") if isinstance(resource, Mapping) else None
    type_property = properties.get("type") if isinstance(properties, Mapping) else None
    if not isinstance(type_property, Mapping):
        return frozenset()
    values = type_property.get("values")
    groups = type_property.get("value_groups")
    catalog: set[str] = set()
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        catalog.update(str(value).casefold() for value in values)
    if isinstance(groups, Sequence) and not isinstance(groups, (str, bytes)):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            if isinstance(group.get("id"), str):
                catalog.add(str(group["id"]).casefold())
            terms = group.get("terms")
            if isinstance(terms, Sequence) and not isinstance(terms, (str, bytes)):
                catalog.update(str(term).casefold() for term in terms)
    for descriptor in descriptors:
        output_schema = descriptor.get("output_schema")
        if not isinstance(output_schema, Mapping):
            continue
        measure_groups = output_schema.get("x-fdai-measure-value-groups")
        if not isinstance(measure_groups, Sequence) or isinstance(measure_groups, (str, bytes)):
            continue
        for group in measure_groups:
            terms = group.get("terms") if isinstance(group, Mapping) else None
            if isinstance(terms, Sequence) and not isinstance(terms, (str, bytes)):
                catalog.update(str(term).casefold() for term in terms)
    return frozenset(catalog)


def _subscription_candidate_is_generic(candidate: str) -> bool:
    """Return whether a captured token is generic scope or descriptive prose."""

    normalized = candidate.casefold()
    if normalized in _GENERIC_SUBSCRIPTION_WORDS or normalized in _KOREAN_SUBSCRIPTION_PARTICLES:
        return True
    return any(
        normalized.endswith(particle)
        and normalized.removesuffix(particle) in _GENERIC_SUBSCRIPTION_WORDS
        for particle in _KOREAN_SUBSCRIPTION_PARTICLES
    )


def operational_time_is_past_hour(value: str) -> bool:
    """Return whether source text explicitly denotes a past one-hour range."""

    return " ".join(value.casefold().split()) in _ONE_HOUR_EXPRESSIONS


__all__ = [
    "GENERIC_SUBSCRIPTION_SCOPE_FILTERS",
    "collection_summary_exact_target_requested",
    "named_subscription_requested",
    "operational_target_is_exact",
    "operational_target_is_generic",
    "operational_time_is_past_hour",
    "resource_catalog_constraints",
]
