"""Deterministic subscription health evidence for Command Deck."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

from fdai.delivery.read_api.routes.chat_inventory_compiler import (
    inventory_query_evidence_authorities,
    inventory_query_status_groups,
    is_specific_inventory_question,
)
from fdai.delivery.read_api.routes.chat_inventory_language import (
    default_inventory_query_language_resolver,
)
from fdai.delivery.read_api.routes.chat_inventory_query import normalize_inventory_value
from fdai.delivery.read_api.routes.chat_inventory_resource_types import (
    default_inventory_resource_type_resolver,
)
from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver
from fdai.rule_catalog.schema.inventory_query_language import QueryEvidenceAuthority

_SCOPE: Final = re.compile(r"\b(?:azure\s+)?subscriptions?\b|구독", re.IGNORECASE)
_HEALTH: Final = re.compile(
    r"\b(?:health|status|state|anomal(?:y|ies)|issues?|degraded|unavailable|check|inspect)\b"
    r"|상태|이상|장애|문제|점검|확인|비정상",
    re.IGNORECASE,
)
_SERVICE_HEALTH: Final = re.compile(
    r"\b(?:service|platform|application|app|fdai)\b.{0,32}"
    r"\b(?:health|outage|incident|issues?|degraded|unavailable|down)\b"
    r"|(?:서비스|플랫폼|애플리케이션|앱|FDAI).{0,20}(?:상태|이상|장애|문제|비정상)",
    re.IGNORECASE,
)
_MUTATION: Final = re.compile(
    r"\b(?:create|delete|restart|scale|update|change|remediate|fix)\b"
    r"|생성|삭제|재시작|스케일|변경|수정|복구",
    re.IGNORECASE,
)
_SUBSCRIPTION_CONTEXT: Final = re.compile(
    r"\b(?:(?:current|active|which|what)\s+(?:azure\s+)?subscription|"
    r"(?:azure\s+)?subscription\s+(?:name|id|details|information))\b"
    r"|(?:현재|지금|어느|어떤)\s*(?:Azure\s*)?구독"
    r"|(?:Azure\s*)?구독\s*(?:이름|정보|아이디|ID)",
    re.IGNORECASE,
)


class SubscriptionHealthProvider(Protocol):
    async def __call__(
        self,
        lookback_seconds: int,
        *,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class ConfigurableSubscriptionHealthProvider(Protocol):
    async def query_health(
        self,
        lookback_seconds: int,
        *,
        include_metrics: bool,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class ResourceTypeFilteredSubscriptionHealthProvider(Protocol):
    async def query_resource_types(
        self,
        lookback_seconds: int,
        *,
        resource_types: tuple[str, ...],
        kind_tokens_by_resource_type: Mapping[str, tuple[str, ...]],
        availability_states: tuple[str, ...],
        include_metrics: bool,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class SubscriptionScopeProvider(Protocol):
    async def describe_scope(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SubscriptionHealthChatTools:
    provider: SubscriptionHealthProvider
    fallback: ChatToolResolver | None = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if needs_subscription_context(prompt):
            if not isinstance(self.provider, SubscriptionScopeProvider):
                result: dict[str, Any] = {
                    "status": "unavailable",
                    "reason": "subscription scope provider is unavailable",
                }
            else:
                try:
                    result = dict(await self.provider.describe_scope())
                except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
                    result = {"status": "unavailable", "reason": type(exc).__name__}
            return {
                "tool": "query_subscription_scope",
                "authority": "server_subscription_scope",
                "result": result,
            }
        if not needs_subscription_health(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        try:
            result = await self._query_health(prompt)
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_subscription_health",
            "authority": "server_subscription_health",
            "query": _status_query(prompt),
            "result": result,
        }

    async def resolve_with_progress(
        self,
        prompt: str,
        *,
        principal_id: str,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> dict[str, Any] | None:
        if needs_subscription_context(prompt):
            return await self.resolve(prompt, principal_id=principal_id)
        if not needs_subscription_health(prompt):
            return await self.resolve(prompt, principal_id=principal_id)
        korean = bool(re.search(r"[\uac00-\ud7a3]", prompt))

        async def observe(progress: Mapping[str, Any]) -> None:
            kind = str(progress.get("kind") or "investigation")
            activity_id = kind.split(".", maxsplit=1)[0]
            label = _progress_label(
                kind,
                korean=korean,
                fallback=str(progress.get("label") or kind),
            )
            event: dict[str, Any] = {
                "event": "activity",
                "activity_id": activity_id,
                "kind": kind,
                "status": str(progress.get("status") or "running"),
                "label": label,
                "completed": progress.get("completed"),
                "total": progress.get("total"),
            }
            await progress_observer(event)
            if kind == "inventory.completed":
                total = _integer(progress.get("total"))
                await progress_observer(
                    {
                        "event": "milestone",
                        "message_id": "subscription-inventory-completed",
                        "text": (
                            f"허용된 범위에서 리소스 {total}개를 찾았습니다. "
                            "Resource Health와 대표 메트릭을 확인합니다."
                            if korean
                            else (
                                f"Found {total} resources in the allowed scope. "
                                "I am checking Resource Health and representative metrics."
                            )
                        ),
                        "agent": "Bragi",
                    }
                )
            if kind == "evidence.correlating":
                await progress_observer(
                    {
                        "event": "milestone",
                        "message_id": "subscription-evidence-correlating",
                        "text": (
                            "상태와 메트릭 근거 수집을 마쳤습니다. "
                            "이상 후보와 누락 범위를 정리합니다."
                            if korean
                            else (
                                "Health and metric evidence collection finished. "
                                "I am summarizing candidates and coverage gaps."
                            )
                        ),
                        "agent": "Bragi",
                    }
                )

        try:
            result = await self._query_health(prompt, progress_observer=observe)
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        await progress_observer(
            {
                "event": "activity",
                "activity_id": "evidence",
                "kind": "evidence.completed",
                "status": "completed" if result.get("status") == "matched" else "unavailable",
                "label": "근거 정리 완료" if korean else "Evidence summary completed",
                "completed": None,
                "total": None,
            }
        )
        return {
            "tool": "query_subscription_health",
            "authority": "server_subscription_health",
            "query": _status_query(prompt),
            "result": result,
        }

    async def _query_health(
        self,
        prompt: str,
        *,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        resolver = default_inventory_resource_type_resolver()
        requested_types = resolver.resolve(prompt)
        provider_types = resolver.provider_types_for(requested_types)
        kind_tokens_by_resource_type = resolver.provider_kind_tokens_for(requested_types)
        language = default_inventory_query_language_resolver()
        include_metrics = language.has(
            language.registry.signals, "diagnosis", prompt
        ) and not _SERVICE_HEALTH.search(prompt)
        availability_states = tuple(
            dict.fromkeys(
                value for group in inventory_query_status_groups(prompt) for value in group.values
            )
        )
        if provider_types and isinstance(
            self.provider, ResourceTypeFilteredSubscriptionHealthProvider
        ):
            return dict(
                await self.provider.query_resource_types(
                    3_600,
                    resource_types=provider_types,
                    kind_tokens_by_resource_type=kind_tokens_by_resource_type,
                    availability_states=availability_states,
                    include_metrics=include_metrics,
                    progress_observer=progress_observer,
                )
            )
        if isinstance(self.provider, ConfigurableSubscriptionHealthProvider):
            return dict(
                await self.provider.query_health(
                    3_600,
                    include_metrics=include_metrics,
                    progress_observer=progress_observer,
                )
            )
        return dict(await self.provider(3_600, progress_observer=progress_observer))


def needs_subscription_health(prompt: str) -> bool:
    if QueryEvidenceAuthority.SUBSCRIPTION_HEALTH in inventory_query_evidence_authorities(prompt):
        return not _MUTATION.search(prompt)
    if is_specific_inventory_question(prompt):
        return False
    language = default_inventory_query_language_resolver()
    asks_for_health = language.has(language.registry.signals, "platform_health", prompt) or bool(
        (_SCOPE.search(prompt) and _HEALTH.search(prompt)) or _SERVICE_HEALTH.search(prompt)
    )
    return asks_for_health and not _MUTATION.search(prompt)


def needs_subscription_context(prompt: str) -> bool:
    return (
        bool(_SUBSCRIPTION_CONTEXT.search(prompt))
        and not is_specific_inventory_question(prompt)
        and not needs_subscription_health(prompt)
    )


def render_subscription_scope_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if evidence.get("tool") != "query_subscription_scope":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if result.get("status") != "matched":
        return (
            "서버에 구성된 Azure 구독 정보를 조회할 수 없습니다."
            if korean
            else "The server-configured Azure subscription information is unavailable."
        )
    display_name = result.get("display_name")
    subscription_id = result.get("subscription_id")
    state = result.get("state")
    source = result.get("source")
    observed_at = result.get("observed_at")
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or not isinstance(subscription_id, str)
        or not subscription_id.strip()
        or not isinstance(state, str)
        or not state.strip()
        or not isinstance(source, str)
        or not source.strip()
        or not isinstance(observed_at, str)
        or not observed_at.strip()
    ):
        return None
    masked_id = _mask_subscription_id(subscription_id)
    if korean:
        return (
            f"현재 서버가 조회하는 Azure 구독은 {display_name}입니다.\n"
            f"- 상태: {state}\n"
            f"- 구독 ID: {masked_id}\n"
            f"근거: Azure Resource Manager, 관찰 시각 {observed_at}."
        )
    return (
        f"The server is currently reading Azure subscription {display_name}.\n"
        f"- State: {state}\n"
        f"- Subscription ID: {masked_id}\n"
        f"Evidence: Azure Resource Manager, observed {observed_at}."
    )


def subscription_scope_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    source = result.get("source")
    observed_at = result.get("observed_at")
    if not isinstance(source, str) or not isinstance(observed_at, str):
        return ()
    return (f"subscription-scope:{source}@{observed_at}",)


def render_subscription_health_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if evidence.get("tool") != "query_subscription_health":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    status = result.get("status")
    if status not in {"matched", "partial"}:
        return (
            "Azure 구독 상태 근거를 조회할 수 없어 정상 여부를 확정하지 않았습니다."
            if korean
            else (
                "Azure subscription health evidence is unavailable, so normal operation "
                "was not confirmed."
            )
        )
    resource_count = _integer(result.get("resource_count"))
    resource_health_unavailable = _integer(result.get("resource_health_unavailable"))
    metric_checked = _integer(result.get("metric_checked"))
    metric_unavailable = _integer(result.get("metric_unavailable"))
    unsupported = _integer(result.get("unsupported_metric_resources"))
    metrics_requested = result.get("metrics_requested") is not False
    metric_observations = [
        item for item in result.get("metric_observations", []) if isinstance(item, Mapping)
    ]
    findings = [item for item in result.get("findings", []) if isinstance(item, Mapping)]
    findings = _filter_findings_by_requested_type(evidence, findings)
    source = str(result.get("source") or "Azure read providers")
    observed_at = str(result.get("observed_at") or "unknown")
    truncated = bool(result.get("truncated"))
    requested_groups = _requested_status_groups(evidence, korean=korean)
    query = evidence.get("query")
    platform_impact = isinstance(query, Mapping) and query.get("platform_impact") is True
    if requested_groups:
        grouped_lines, grouped_count = _grouped_finding_lines(
            findings,
            requested_groups,
            korean=korean,
        )
        summary = (
            f"허용된 Azure 범위에서 리소스 {resource_count}개를 확인했고 요청한 상태의 "
            f"리소스 {grouped_count}개를 찾았습니다."
            if korean
            else (
                f"Checked {resource_count} resources in the allowed Azure scope and found "
                f"{grouped_count} resource(s) in the requested states."
            )
        )
    elif platform_impact:
        grouped_lines = _finding_lines(findings, korean=korean)
        platform_count, customer_count, unknown_count = _cause_counts(findings)
        summary = (
            f"Azure 플랫폼 영향으로 분류된 리소스는 {platform_count}개입니다. "
            f"Customer-initiated {customer_count}개, 원인 미확정 {unknown_count}개입니다."
            if korean
            else (
                f"{platform_count} resource(s) were classified as Azure platform impact; "
                f"{customer_count} were customer-initiated and {unknown_count} were unclassified."
            )
        )
    else:
        grouped_lines = _finding_lines(findings, korean=korean)
        summary = (
            f"허용된 Azure 범위에서 리소스 {resource_count}개를 확인했고 "
            f"상태 이상 후보 {len(findings)}개를 찾았습니다."
            if korean
            else (
                f"Checked {resource_count} resources in the allowed Azure scope and found "
                f"{len(findings)} health candidate(s)."
            )
        )
    if korean:
        lines = [summary]
        lines.extend(grouped_lines)
        lines.extend(_metric_observation_lines(metric_observations, korean=True))
        metric_summary = (
            f"메트릭 확인: {metric_checked}개, 조회 불가 {metric_unavailable}개, "
            f"미지원 {unsupported}개."
            if metrics_requested
            else "대표 메트릭: 요청되지 않음."
        )
        lines.append(
            f"Resource Health 조회 불가 범위 {resource_health_unavailable}개. {metric_summary}"
        )
        lines.append(f"근거: {source}, 관찰 시각 {observed_at}.")
        if truncated:
            lines.append("조회 한도에 도달했으므로 추가 리소스나 후보가 있을 수 있습니다.")
        if status == "partial":
            lines.append(
                "일부 Resource Health 또는 메트릭 근거가 조회 불가이거나 미지원이므로 "
                "전체 정상 상태를 확정하지 않았습니다."
            )
        return "\n".join(lines)
    lines = [summary]
    lines.extend(grouped_lines)
    lines.extend(_metric_observation_lines(metric_observations, korean=False))
    metric_summary = (
        f"Metrics: {metric_checked} checked, {metric_unavailable} unavailable, "
        f"{unsupported} unsupported."
        if metrics_requested
        else "Representative metrics were not requested."
    )
    lines.append(
        f"Resource Health: {resource_health_unavailable} scope(s) unavailable. {metric_summary}"
    )
    lines.append(f"Evidence: {source}, observed {observed_at}.")
    if truncated:
        lines.append("The bounded query limit was reached; additional resources may exist.")
    if status == "partial":
        lines.append(
            "Some Resource Health or metric evidence was unavailable or unsupported, so "
            "complete normal operation was not confirmed."
        )
    return "\n".join(lines)


def subscription_health_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    source = result.get("source")
    observed_at = result.get("observed_at")
    if not isinstance(source, str) or not isinstance(observed_at, str):
        return ()
    return (f"subscription-health:{source}@{observed_at}",)


def requested_subscription_health_findings_are_grounded(
    evidence: Mapping[str, Any],
) -> bool:
    """Return whether partial evidence contains a positive requested-state finding."""

    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "partial":
        return False
    groups = _requested_status_groups(evidence, korean=False)
    if not groups:
        return False
    requested_values = {value for _label, values in groups for value in values}
    findings = result.get("findings")
    return isinstance(findings, list) and any(
        isinstance(finding, Mapping)
        and normalize_inventory_value(finding.get("status")) in requested_values
        for finding in findings
    )


def _finding_lines(findings: list[Mapping[str, Any]], *, korean: bool) -> list[str]:
    if not findings:
        return [
            "- 현재 조회 범위에서 명시적인 이상 근거가 발견되지 않았습니다."
            if korean
            else "- No explicit anomaly evidence was observed in the bounded scope."
        ]
    lines: list[str] = []
    for finding in findings[:20]:
        name = str(finding.get("resource_name") or "unknown")
        kind = str(finding.get("kind") or "unknown")
        status = str(finding.get("status") or "unknown")
        if kind == "resource_health":
            title = str(finding.get("title") or "unknown")
            reason = str(finding.get("reason") or "unknown")
            resource_type = str(finding.get("resource_type") or "unknown")
            resource_group = str(finding.get("resource_group") or "unknown")
            if korean:
                explanation = (
                    "Azure 플랫폼 장애가 아니라 사용자 또는 자동화 작업으로 시작된 "
                    "상태를 나타냅니다. 실행 주체는 Activity Log 확인 전에는 특정할 수 없습니다."
                    if reason.casefold() == "customer initiated"
                    else f"Resource Health 원인 분류는 {reason}입니다."
                )
                lines.append(
                    f"- {name}: Resource Health {status} ({title}), type {resource_type}, "
                    f"resource group {resource_group}. {explanation}"
                )
            else:
                explanation = (
                    "This indicates a user- or automation-initiated state rather than an "
                    "Azure platform incident. The actor requires Activity Log evidence."
                    if reason.casefold() == "customer initiated"
                    else f"Resource Health classified the cause as {reason}."
                )
                lines.append(
                    f"- {name}: Resource Health {status} ({title}), type {resource_type}, "
                    f"resource group {resource_group}. {explanation}"
                )
            continue
        metric = finding.get("metric")
        value = finding.get("value")
        detail = f", {metric}={value}" if isinstance(metric, str) else ""
        lines.append(f"- {name}: {kind}, {status}{detail}")
    return lines


def _metric_observation_lines(
    observations: list[Mapping[str, Any]],
    *,
    korean: bool,
) -> list[str]:
    lines: list[str] = []
    for observation in observations[:20]:
        name = str(observation.get("resource_name") or "unknown")
        metric = str(observation.get("metric") or "unknown")
        value = observation.get("value")
        threshold = observation.get("threshold")
        comparison = str(observation.get("comparison") or "unknown")
        anomalous = observation.get("anomalous") is True
        if korean:
            status = "임계값 초과" if anomalous else "임계값 이내"
        else:
            status = "over threshold" if anomalous else "within threshold"
        lines.append(f"- {name}: {metric}={value}, threshold {comparison} {threshold} ({status}).")
    return lines


def _status_query(prompt: str) -> dict[str, object]:
    groups = inventory_query_status_groups(prompt)
    requested_types = default_inventory_resource_type_resolver().resolve(prompt)
    language = default_inventory_query_language_resolver()
    return {
        "platform_impact": language.has(language.registry.signals, "platform_health", prompt),
        "requested_resource_types": list(requested_types),
        "requested_status_groups": [
            {"id": group.id, "values": list(group.values), "labels": dict(group.labels)}
            for group in groups
        ],
    }


def _cause_counts(findings: list[Mapping[str, Any]]) -> tuple[int, int, int]:
    platform = 0
    customer = 0
    unknown = 0
    for finding in findings:
        if finding.get("kind") != "resource_health":
            continue
        reason = normalize_inventory_value(finding.get("reason"))
        if reason == "platform initiated":
            platform += 1
        elif reason == "customer initiated":
            customer += 1
        else:
            unknown += 1
    return platform, customer, unknown


def _filter_findings_by_requested_type(
    evidence: Mapping[str, Any],
    findings: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    query = evidence.get("query")
    raw_types = query.get("requested_resource_types") if isinstance(query, Mapping) else None
    if (
        not isinstance(raw_types, list)
        or not raw_types
        or not all(isinstance(item, str) for item in raw_types)
    ):
        return findings
    resolver = default_inventory_resource_type_resolver()
    accepted = {
        normalize_inventory_value(item)
        for item in (*raw_types, *resolver.provider_types_for(raw_types))
    }
    return [
        finding
        for finding in findings
        if normalize_inventory_value(finding.get("resource_type")) in accepted
    ]


def _requested_status_groups(
    evidence: Mapping[str, Any],
    *,
    korean: bool,
) -> list[tuple[str, tuple[str, ...]]]:
    query = evidence.get("query")
    raw_groups = query.get("requested_status_groups") if isinstance(query, Mapping) else None
    if not isinstance(raw_groups, list):
        return []
    groups: list[tuple[str, tuple[str, ...]]] = []
    for item in raw_groups:
        if not isinstance(item, Mapping):
            continue
        values = item.get("values")
        labels = item.get("labels")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            continue
        locale = "ko" if korean else "en"
        label = labels.get(locale) if isinstance(labels, Mapping) else None
        if not isinstance(label, str):
            label = str(item.get("id") or "Status")
        groups.append((label, tuple(normalize_inventory_value(value) for value in values)))
    return groups


def _grouped_finding_lines(
    findings: list[Mapping[str, Any]],
    groups: list[tuple[str, tuple[str, ...]]],
    *,
    korean: bool,
) -> tuple[list[str], int]:
    lines: list[str] = []
    matched_count = 0
    for label, values in groups:
        matched = [
            finding
            for finding in findings
            if normalize_inventory_value(finding.get("status")) in values
        ]
        matched_count += len(matched)
        lines.append(f"**{label}**")
        if matched:
            lines.extend(_finding_lines(matched, korean=korean))
        else:
            lines.append(
                "- 확인한 근거에서는 관찰되지 않았습니다."
                if korean
                else "- Not observed in the checked evidence."
            )
    return lines, matched_count


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _mask_subscription_id(value: str) -> str:
    stripped = value.strip()
    if len(stripped) <= 8:
        return "****"
    return f"{stripped[:4]}...{stripped[-4:]}"


def _progress_label(kind: str, *, korean: bool, fallback: str) -> str:
    if not korean:
        return fallback
    return {
        "inventory.querying": "리소스 검색 중",
        "inventory.completed": "리소스 검색 완료",
        "resource-health.querying": "Resource Health 확인 중",
        "resource-health.completed": "Resource Health 확인 완료",
        "metrics.querying": "대표 메트릭 확인 중",
        "metrics.completed": "대표 메트릭 확인 완료",
        "evidence.correlating": "상태 근거 상관분석 중",
    }.get(kind, fallback)


__all__ = [
    "SubscriptionHealthChatTools",
    "SubscriptionHealthProvider",
    "SubscriptionScopeProvider",
    "needs_subscription_context",
    "needs_subscription_health",
    "requested_subscription_health_findings_are_grounded",
    "render_subscription_scope_answer",
    "render_subscription_health_answer",
    "subscription_scope_evidence_refs",
    "subscription_health_evidence_refs",
]
