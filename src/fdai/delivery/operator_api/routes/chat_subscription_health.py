"""Deterministic subscription health evidence for Command Deck."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Final, Protocol, runtime_checkable

from fdai.delivery.operator_api.routes.chat_inventory_compiler import (
    inventory_query_evidence_authorities,
    inventory_query_status_groups,
    is_specific_inventory_question,
)
from fdai.delivery.operator_api.routes.chat_inventory_language import (
    default_inventory_query_language_resolver,
)
from fdai.delivery.operator_api.routes.chat_inventory_query import normalize_inventory_value
from fdai.delivery.operator_api.routes.chat_inventory_resource_types import (
    default_inventory_resource_type_resolver,
)
from fdai.delivery.operator_api.routes.chat_log_query import needs_log_query
from fdai.delivery.operator_api.routes.chat_system_health import ChatToolResolver
from fdai.delivery.operator_api.routes.chat_turn_plan import TurnTool
from fdai.rule_catalog.schema.inventory_query_language import QueryEvidenceAuthority
from fdai.shared.providers.observation import LogQueryProvider, ObservationError

_SCOPE: Final = re.compile(
    r"\b(?:azure\s+)?subscriptions?\b|구독"
    r"|\b(?:configured|allowed|current)\s+(?:azure\s+)?scope\b"
    r"|구성된\s*범위|허용된\s*범위",
    re.IGNORECASE,
)
_HEALTH: Final = re.compile(
    r"\b(?:health|status|state|anomal(?:y|ies)|issues?|degraded|unavailable|check|inspect)\b"
    r"|상태|이상|장애|문제|점검|확인|비정상",
    re.IGNORECASE,
)
_SERVICE_HEALTH: Final = re.compile(
    r"\b(?:service(?!-level)|platform|application|app|fdai)\b.{0,32}"
    r"\b(?:health|outage|incident|issues?|degraded|unavailable|down)\b"
    r"|(?:서비스|플랫폼|애플리케이션|앱|FDAI).{0,20}(?:상태|이상|장애|문제|비정상)",
    re.IGNORECASE,
)
_MUTATION: Final = re.compile(
    r"\b(?:create|delete|restart|scale|update|change|remediate|fix)\b"
    r"|생성|삭제|재시작|스케일|변경|수정|복구",
    re.IGNORECASE,
)
_STRONG_MUTATION: Final = re.compile(
    r"\b(?:create|delete|restart|scale|update|remediate|fix)\b"
    r"|생성|삭제|재시작|스케일|수정|복구",
    re.IGNORECASE,
)
_SUBSCRIPTION_CONTEXT: Final = re.compile(
    r"\b(?:(?:current|active|which|what)\s+(?:azure\s+)?subscription|"
    r"(?:azure\s+)?subscription\s+(?:name|id|details|information))\b"
    r"|(?:현재|지금|어느|어떤)\s*(?:Azure\s*)?구독"
    r"|(?:Azure\s*)?구독\s*(?:이름|정보|아이디|ID)",
    re.IGNORECASE,
)
_HEALTH_COVERAGE: Final = re.compile(
    r"\b(?:health checks?|health evidence)\b.{0,64}"
    r"\b(?:authorization|permission|scope|blocked|unavailable)\b|"
    r"\b(?:authorization|permission|scope)\b.{0,48}"
    r"\b(?:block(?:ed|ing)?|limits?|unavailable)\b.{0,48}"
    r"\b(?:health checks?|health evidence)\b|"
    r"(?:상태|헬스|건강|근거).{0,20}(?:점검|확인|읽기|조회).{0,48}"
    r"(?:권한|범위|차단|막힌|조회 불가)|"
    r"(?:권한|범위).{0,24}(?:차단|막힌|조회 불가).{0,24}(?:상태|헬스|건강).{0,12}점검",
    re.IGNORECASE,
)
_CURRENT_HEALTH_TIMELINE: Final = re.compile(
    r"^(?=[\s\S]{0,500}\bresource health\b)"
    r"(?=[\s\S]{0,500}(?:\b(?:first observed|began|started|onset)\b|언제부터|최초로?\s*관측|시작))"
    r"(?=[\s\S]{0,500}(?:\b(?:customer|platform)[ -]initiated\b|고객\s*기인|플랫폼\s*기인))",
    re.IGNORECASE,
)
_CPU_DIAGNOSIS: Final = re.compile(
    r"\bcpu\b.{0,48}\b(?:spike|spikes|spiked|abnormal|unusual|high|surge|usage|utilization)\b|"
    r"\b(?:spike|spikes|abnormal|unusual|high)\b.{0,48}\bcpu\b|"
    r"CPU.{0,32}(?:급증|비정상|상승|사용률|튀|튄)",
    re.IGNORECASE,
)
_MEMORY_DIAGNOSIS: Final = re.compile(
    r"\bmemory\b.{0,48}\b(?:pressure|shortage|low|high|usage|utilization|exhausted)\b|"
    r"\b(?:pressure|shortage|low|high)\b.{0,48}\bmemory\b|"
    r"(?:메모리).{0,32}(?:부족|모자란|압박|고갈|사용률|높|상승|달라)",
    re.IGNORECASE,
)
_BEFORE_AFTER_COMPARISON: Final = re.compile(
    r"\b(?:before|prior to)\b.{0,48}\b(?:after|following)\b.{0,48}"
    r"\b(?:incident|outage)\b|"
    r"\b(?:incident|outage)\b.{0,48}\b(?:before|prior to)\b.{0,48}"
    r"\b(?:after|following)\b|"
    r"(?:인시던트|장애).{0,24}(?:전후|앞뒤|이전과 이후)|"
    r"(?:전후|앞뒤|이전과 이후).{0,24}(?:인시던트|장애)",
    re.IGNORECASE,
)
_ERROR_CHANGE_CORRELATION: Final = re.compile(
    r"\b(?:error rate|error-rate|errors?)\b.{0,64}"
    r"\b(?:correlate|correlation|deployment|configuration|change|increase|spike)\b|"
    r"\b(?:deployment|configuration|change)\b.{0,64}"
    r"\b(?:error rate|error-rate|errors?)\b|"
    r"(?:오류율|에러).{0,48}(?:급증|상승|오른|늘어난|배포|설정 변경|변경|연관|겹쳐)|"
    r"(?:배포|설정 변경).{0,48}(?:오류율|에러)",
    re.IGNORECASE,
)
_POD_DIAGNOSIS: Final = re.compile(
    r"\b(?:this\s+)?pod\b.{0,48}\b(?:restart|restarting|throttl|reason|cause)\w*\b|"
    r"(?:이\s*)?(?:파드|pod).{0,40}(?:재시작|throttl|이유|원인)",
    re.IGNORECASE,
)
_CAPACITY_DIAGNOSIS: Final = re.compile(
    r"\b(?:capacity).{0,64}(?:traffic|load|demand|trend|handle|enough|headroom)\b|"
    r"\b(?:traffic|load|demand|trend|headroom).{0,64}"
    r"(?:capacity|handle|enough|headroom)\b|"
    r"\bheadroom\b.{0,48}\b(?:demand|load|traffic)\s+trend\b|"
    r"(?:용량|capacity).{0,48}(?:트래픽|부하|증가|감당|충분)",
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
        include_service_health: bool = False,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class HistoricalSubscriptionHealthProvider(Protocol):
    async def query_health_history(
        self,
        lookback_seconds: int,
        *,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class ComparativeSubscriptionHealthProvider(Protocol):
    async def query_metric_comparison(
        self,
        *,
        anchor_at: str,
        metric_family: str,
        window_seconds: int,
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
    log_query_provider: LogQueryProvider | None = None

    def turn_tools(self) -> tuple[TurnTool, ...]:
        return (
            TurnTool(
                name="query_subscription_health",
                description=(
                    "Read bounded Resource Health, service health, and representative metric "
                    "evidence from the server-owned Azure scope."
                ),
                side_effect_class="read",
                argument_schema={
                    "type": "object",
                    "properties": {
                        "lookback_seconds": {"type": "integer", "minimum": 60, "maximum": 86_400},
                        "include_metrics": {"type": "boolean"},
                        "include_service_health": {"type": "boolean"},
                    },
                    "required": ["lookback_seconds", "include_metrics", "include_service_health"],
                    "additionalProperties": False,
                },
            ),
        )

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if tool_name != "query_subscription_health":
            fallback = getattr(self.fallback, "resolve_planned", None)
            if callable(fallback):
                result = await fallback(tool_name, arguments, principal_id=principal_id)
                return dict(result) if isinstance(result, Mapping) else None
            return None
        lookback_seconds = arguments.get("lookback_seconds")
        include_metrics = arguments.get("include_metrics")
        include_service_health = arguments.get("include_service_health")
        if (
            not isinstance(lookback_seconds, int)
            or isinstance(lookback_seconds, bool)
            or not 60 <= lookback_seconds <= 86_400
            or not isinstance(include_metrics, bool)
            or not isinstance(include_service_health, bool)
            or set(arguments) != {"lookback_seconds", "include_metrics", "include_service_health"}
        ):
            raise ValueError("planned subscription health arguments are invalid")
        try:
            if isinstance(self.provider, ConfigurableSubscriptionHealthProvider):
                raw_result = await self.provider.query_health(
                    lookback_seconds,
                    include_metrics=include_metrics,
                    include_service_health=include_service_health,
                )
            else:
                raw_result = await self.provider(lookback_seconds)
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            raw_result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_subscription_health",
            "authority": "server_subscription_health",
            "query": dict(arguments),
            "result": dict(raw_result),
        }

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
            result = _normalize_health_coverage(await self._query_health(prompt))
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_subscription_health",
            "authority": "server_subscription_health",
            "query": _status_query(prompt),
            "result": result,
        }

    async def resolve_with_context(
        self,
        prompt: str,
        *,
        principal_id: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        error_change_correlation = bool(_ERROR_CHANGE_CORRELATION.search(prompt))
        if error_change_correlation:
            return await self._resolve_error_change_correlation(prompt, context=context)
        diagnostic_metric = _diagnostic_metric(prompt)
        if diagnostic_metric is None or not _BEFORE_AFTER_COMPARISON.search(prompt):
            return await self.resolve(prompt, principal_id=principal_id)
        resource_context = context.get("resource_context") if context is not None else None
        anchor_at = (
            resource_context.get("event_at") if isinstance(resource_context, Mapping) else None
        )
        if not isinstance(anchor_at, str) or not anchor_at:
            result: Mapping[str, Any] = {
                "status": "unavailable",
                "reason": "incident_anchor_unavailable",
                "source": "metric-comparison-contract",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        elif not isinstance(self.provider, ComparativeSubscriptionHealthProvider):
            result = {
                "status": "unavailable",
                "reason": "metric_comparison_provider_unavailable",
                "source": "metric-comparison-contract",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        else:
            try:
                result = await self.provider.query_metric_comparison(
                    anchor_at=anchor_at,
                    metric_family=diagnostic_metric,
                    window_seconds=3_600,
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
                result = {
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                    "source": "metric-comparison-provider",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "truncated": False,
                }
        return {
            "tool": "query_subscription_health",
            "authority": "server_subscription_health",
            "query": _status_query(prompt),
            "result": dict(result),
        }

    async def _resolve_error_change_correlation(
        self,
        prompt: str,
        *,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        del prompt
        resource_context = context.get("resource_context") if context is not None else None
        anchor_at = (
            resource_context.get("event_at") if isinstance(resource_context, Mapping) else None
        )
        resource_group = (
            resource_context.get("resource_group")
            if isinstance(resource_context, Mapping)
            else None
        )
        if not isinstance(anchor_at, str) or not anchor_at:
            result: Mapping[str, Any] = {
                "status": "unavailable",
                "reason": "incident_anchor_unavailable",
                "source": "telemetry-activity-join",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        elif self.log_query_provider is None:
            result = {
                "status": "unavailable",
                "reason": "telemetry_activity_join_unavailable",
                "source": "telemetry-activity-join",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        else:
            try:
                anchor = datetime.fromisoformat(anchor_at.replace("Z", "+00:00"))
                if anchor.tzinfo is None:
                    raise ValueError("incident anchor MUST be timezone-aware")
                anchor = anchor.astimezone(UTC)
                since = anchor.timestamp() - 3_600
                until = anchor.timestamp() + 3_600
                group_filter = (
                    f"| where ResourceGroup =~ '{_kql_text(resource_group)}' "
                    if isinstance(resource_group, str) and resource_group
                    else ""
                )
                query = (
                    "union "
                    "(AppRequests "
                    f"| where TimeGenerated between (unixtime_seconds_todatetime({since}) .. "
                    f"unixtime_seconds_todatetime({until})) "
                    "| summarize request_count=count(), error_count=countif(Success == false "
                    "or ResultCode startswith '5') by TimeGenerated=bin(TimeGenerated, 5m) "
                    "| extend evidence_kind='error_rate'), "
                    "(AzureActivity "
                    f"| where TimeGenerated between (unixtime_seconds_todatetime({since}) .. "
                    f"unixtime_seconds_todatetime({until})) "
                    "| where ActivityStatusValue =~ 'Success' "
                    f"{group_filter}"
                    "| project TimeGenerated, evidence_kind='change', OperationNameValue, "
                    "ResourceGroup) | order by TimeGenerated asc"
                )
                query_result = await self.log_query_provider.query_log(
                    query=query,
                    window="PT2H",
                    max_rows=100,
                )
                rows = [dict(row) for row in query_result.rows]
                result = _correlation_result(
                    rows,
                    anchor_at=anchor_at,
                    observed_at=datetime.now(UTC).isoformat(),
                    truncated=query_result.truncated,
                )
            except (ObservationError, ValueError) as exc:
                result = {
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                    "source": "azure-monitor-logs-activity-join",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "truncated": False,
                }
        return {
            "tool": "query_subscription_health",
            "authority": "server_subscription_health",
            "query": _status_query("error-rate change correlation"),
            "result": dict(result),
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
            result = _normalize_health_coverage(
                await self._query_health(prompt, progress_observer=observe)
            )
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
        platform_impact = language.has(language.registry.signals, "platform_health", prompt)
        health_history = language.has(language.registry.signals, "health_history", prompt)
        current_health_timeline = bool(_CURRENT_HEALTH_TIMELINE.search(prompt))
        health_coverage = bool(_HEALTH_COVERAGE.search(prompt))
        diagnostic_metric = _diagnostic_metric(prompt)
        metric_comparison = diagnostic_metric is not None and bool(
            _BEFORE_AFTER_COMPARISON.search(prompt)
        )
        error_change_correlation = bool(_ERROR_CHANGE_CORRELATION.search(prompt))
        pod_diagnosis = bool(_POD_DIAGNOSIS.search(prompt))
        capacity_diagnosis = bool(_CAPACITY_DIAGNOSIS.search(prompt))
        status_groups = inventory_query_status_groups(prompt)
        if diagnostic_metric is not None:
            status_groups = tuple(group for group in status_groups if group.id != "unhealthy")
        if health_history:
            if not isinstance(self.provider, HistoricalSubscriptionHealthProvider):
                raise RuntimeError("subscription health history provider is unavailable")
            lookback_seconds = min(
                language.parse_window_seconds(prompt)
                or language.registry.default_activity_lookback_seconds,
                86_400,
            )
            return dict(
                await self.provider.query_health_history(
                    lookback_seconds,
                    progress_observer=progress_observer,
                )
            )
        if metric_comparison:
            return {
                "status": "unavailable",
                "reason": "incident_anchor_unavailable",
                "source": "metric-comparison-contract",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        if error_change_correlation:
            return {
                "status": "unavailable",
                "reason": "telemetry_activity_join_unavailable",
                "source": "telemetry-correlation-contract",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        if pod_diagnosis:
            return {
                "status": "unavailable",
                "reason": "pod_selector_required",
                "source": "kubernetes-diagnostic-contract",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        if capacity_diagnosis:
            return {
                "status": "unavailable",
                "reason": "capacity_trend_provider_unavailable",
                "source": "capacity-diagnostic-contract",
                "observed_at": datetime.now(UTC).isoformat(),
                "truncated": False,
            }
        include_metrics = not current_health_timeline and (
            health_coverage
            or diagnostic_metric is not None
            or (
                language.has(language.registry.signals, "diagnosis", prompt) and not platform_impact
            )
        )
        availability_states = (
            ()
            if platform_impact
            else tuple(dict.fromkeys(value for group in status_groups for value in group.values))
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
                    include_service_health=platform_impact or health_coverage,
                    progress_observer=progress_observer,
                )
            )
        return dict(await self.provider(3_600, progress_observer=progress_observer))


def needs_subscription_health(prompt: str) -> bool:
    if needs_log_query(prompt):
        return False
    if _POD_DIAGNOSIS.search(prompt) or _CAPACITY_DIAGNOSIS.search(prompt):
        return True
    diagnostic_metric = _diagnostic_metric(prompt)
    if diagnostic_metric is not None and _BEFORE_AFTER_COMPARISON.search(prompt):
        return True
    if _ERROR_CHANGE_CORRELATION.search(prompt):
        return True
    if _HEALTH_COVERAGE.search(prompt):
        return not _MUTATION.search(prompt)
    if _CURRENT_HEALTH_TIMELINE.search(prompt):
        return not _MUTATION.search(prompt)
    if diagnostic_metric is not None:
        return not _MUTATION.search(prompt)
    if QueryEvidenceAuthority.SUBSCRIPTION_HEALTH in inventory_query_evidence_authorities(prompt):
        return not _MUTATION.search(prompt)
    if is_specific_inventory_question(prompt):
        return False
    language = default_inventory_query_language_resolver()
    catalog_health_read = language.has(
        language.registry.signals, "platform_health", prompt
    ) or language.has(language.registry.signals, "health_history", prompt)
    if catalog_health_read:
        return not _STRONG_MUTATION.search(prompt)
    asks_for_health = (_SCOPE.search(prompt) and _HEALTH.search(prompt)) or _SERVICE_HEALTH.search(
        prompt
    )
    return bool(asks_for_health) and not _MUTATION.search(prompt)


def needs_subscription_health_context(prompt: str) -> bool:
    diagnostic_metric = _diagnostic_metric(prompt)
    return (
        diagnostic_metric is not None and bool(_BEFORE_AFTER_COMPARISON.search(prompt))
    ) or bool(_ERROR_CHANGE_CORRELATION.search(prompt))


def _normalize_health_coverage(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "matched":
        return result
    incomplete = result.get("truncated") is True or any(
        _integer(result.get(key)) > 0
        for key in (
            "resource_health_unavailable",
            "service_health_unavailable",
            "metric_unavailable",
        )
    )
    if not incomplete:
        return result
    return {**result, "status": "partial"}


def _diagnostic_metric(prompt: str) -> str | None:
    if _CPU_DIAGNOSIS.search(prompt):
        return "cpu"
    if _MEMORY_DIAGNOSIS.search(prompt):
        return "memory"
    return None


def needs_subscription_context(prompt: str) -> bool:
    language = default_inventory_query_language_resolver()
    return (
        bool(_SUBSCRIPTION_CONTEXT.search(prompt))
        and not language.has(language.registry.signals, "resource_subject", prompt)
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
    query = evidence.get("query")
    metric_comparison = isinstance(query, Mapping) and query.get("metric_comparison") is True
    error_change_correlation = (
        isinstance(query, Mapping) and query.get("error_change_correlation") is True
    )
    pod_diagnosis = isinstance(query, Mapping) and query.get("pod_diagnosis") is True
    capacity_diagnosis = isinstance(query, Mapping) and query.get("capacity_diagnosis") is True
    status = result.get("status")
    if status not in {"matched", "partial"}:
        if metric_comparison and result.get("reason") == "incident_anchor_unavailable":
            return (
                "비교할 인시던트 anchor가 없어 전후 메트릭 window를 조회하지 않았습니다. "
                "인시던트를 선택한 뒤 다시 시도하세요."
                if korean
                else (
                    "No incident anchor was available, so separate before and after metric "
                    "windows were not queried. Select an incident and try again."
                )
            )
        if (
            error_change_correlation
            and result.get("reason") == "telemetry_activity_join_unavailable"
        ):
            return (
                "오류율 metric window와 배포 또는 설정 변경 activity를 함께 조회하는 provider가 "
                "구성되지 않아 상관관계를 확정하지 않았습니다."
                if korean
                else (
                    "No provider is configured to join an error-rate metric window with "
                    "deployment or configuration activity, so no correlation was claimed."
                )
            )
        if error_change_correlation and result.get("reason") == "incident_anchor_unavailable":
            return (
                "비교할 인시던트 anchor가 없어 오류율과 변경 activity를 조회하지 않았습니다."
                if korean
                else (
                    "No incident anchor was available, so error-rate and change activity "
                    "were not queried."
                )
            )
        if pod_diagnosis and result.get("reason") == "pod_selector_required":
            return (
                "정확한 pod name 또는 선택된 pod context가 없어 재시작이나 throttling 원인을 "
                "조회하지 않았습니다."
                if korean
                else (
                    "An exact pod name or selected pod context is required before restart or "
                    "throttling causes can be queried."
                )
            )
        if capacity_diagnosis and result.get("reason") == "capacity_trend_provider_unavailable":
            return (
                "관측 부하와 자원 한도를 함께 평가하는 capacity trend provider가 구성되지 않아 "
                "현재 용량의 충분 여부를 확정하지 않았습니다."
                if korean
                else (
                    "No capacity trend provider is configured to evaluate observed load against "
                    "resource limits, so capacity sufficiency was not confirmed."
                )
            )
        return (
            "Azure 구독 상태 근거를 조회할 수 없어 정상 여부를 확정하지 않았습니다."
            if korean
            else (
                "Azure subscription health evidence is unavailable, so normal operation "
                "was not confirmed."
            )
        )
    if metric_comparison:
        return _render_metric_comparison_answer(result, korean=korean)
    if error_change_correlation:
        return _render_error_change_correlation_answer(result, korean=korean)
    resource_count = _integer(result.get("resource_count"))
    resource_health_unavailable = _integer(result.get("resource_health_unavailable"))
    service_health_unavailable = _integer(result.get("service_health_unavailable"))
    service_health_requested = result.get("service_health_requested") is True
    active_service_issues = _integer(result.get("active_service_issue_count"))
    active_service_issue_resources = _integer(result.get("active_service_issue_resource_count"))
    active_maintenance = _integer(result.get("active_planned_maintenance_count"))
    active_maintenance_resources = _integer(result.get("active_planned_maintenance_resource_count"))
    active_advisories = _integer(result.get("active_health_advisory_count"))
    active_advisory_resources = _integer(result.get("active_health_advisory_resource_count"))
    service_health_events = [
        item for item in result.get("service_health_events", []) if isinstance(item, Mapping)
    ]
    metric_checked = _integer(result.get("metric_checked"))
    metric_unavailable = _integer(result.get("metric_unavailable"))
    unsupported = _integer(result.get("unsupported_metric_resources"))
    metrics_requested = result.get("metrics_requested") is not False
    metric_observations = [
        item for item in result.get("metric_observations", []) if isinstance(item, Mapping)
    ]
    findings = subscription_health_findings(evidence)
    source = str(result.get("source") or "Azure read providers")
    observed_at = str(result.get("observed_at") or "unknown")
    truncated = bool(result.get("truncated"))
    requested_groups = _requested_status_groups(evidence, korean=korean)
    platform_impact = isinstance(query, Mapping) and query.get("platform_impact") is True
    health_history = isinstance(query, Mapping) and query.get("health_history") is True
    current_health_timeline = (
        isinstance(query, Mapping) and query.get("current_health_timeline") is True
    )
    health_coverage = isinstance(query, Mapping) and query.get("health_coverage") is True
    diagnostic_metric = (
        str(query.get("diagnostic_metric"))
        if isinstance(query, Mapping) and query.get("diagnostic_metric") in {"cpu", "memory"}
        else None
    )
    if diagnostic_metric is not None:
        metric_observations = [
            item
            for item in metric_observations
            if diagnostic_metric in str(item.get("metric") or "").casefold()
        ]
    if health_history:
        history_events = [
            item for item in result.get("health_history_events", []) if isinstance(item, Mapping)
        ]
        lookback_seconds = (
            _integer(query.get("lookback_seconds")) if isinstance(query, Mapping) else 0
        )
        return _render_health_history_answer(
            history_events,
            lookback_seconds=lookback_seconds,
            source=source,
            observed_at=observed_at,
            status=str(status),
            truncated=truncated,
            korean=korean,
        )
    if health_coverage:
        return _render_health_coverage_answer(
            resource_health_unavailable=resource_health_unavailable,
            service_health_unavailable=service_health_unavailable,
            metric_unavailable=metric_unavailable,
            unsupported=unsupported,
            source=source,
            observed_at=observed_at,
            status=str(status),
            truncated=truncated,
            korean=korean,
        )
    if current_health_timeline:
        grouped_lines = _finding_lines(findings, korean=korean, include_timeline=True)
        if not findings:
            grouped_lines = [
                (
                    "- 현재 Resource Health 이상이 없어 customer-initiated 또는 "
                    "platform-initiated 분류 대상이 없습니다."
                )
                if korean
                else (
                    "- No current Resource Health anomaly requires customer-initiated or "
                    "platform-initiated classification."
                )
            ]
        summary = (
            f"허용된 Azure 범위에서 리소스 {resource_count}개를 확인했고 현재 Resource Health "
            f"이상 {len(findings)}개를 찾았습니다."
            if korean
            else (
                f"Checked {resource_count} resources in the allowed Azure scope and found "
                f"{len(findings)} current Resource Health anomaly finding(s)."
            )
        )
    elif requested_groups:
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
    elif diagnostic_metric is not None:
        grouped_lines = []
        anomalous_count = sum(item.get("anomalous") is True for item in metric_observations)
        summary = (
            f"허용된 Azure 범위에서 {diagnostic_metric} 메트릭 관측 "
            f"{len(metric_observations)}개를 확인했고 임계값 초과 {anomalous_count}개를 찾았습니다."
            if korean
            else (
                f"Checked {len(metric_observations)} {diagnostic_metric} metric observation(s) "
                f"in the allowed Azure scope; {anomalous_count} exceeded the threshold."
            )
        )
    elif platform_impact:
        grouped_lines = [
            *_service_health_event_lines(service_health_events, korean=korean),
            *_finding_lines(findings, korean=korean),
        ]
        platform_count, customer_count, unknown_count = _cause_counts(findings)
        summary = (
            f"Service Health에서 활성 Azure 장애 이벤트 {active_service_issues}개와 "
            f"영향받는 관리형 리소스 {active_service_issue_resources}개를 확인했습니다. "
            f"활성 계획 유지 관리 {active_maintenance}개가 리소스 "
            f"{active_maintenance_resources}개에, 활성 권고 {active_advisories}개가 리소스 "
            f"{active_advisory_resources}개에 연결됩니다. Resource Health에서는 Azure 플랫폼 "
            f"영향 {platform_count}개, Customer-initiated {customer_count}개, 원인 미확정 "
            f"{unknown_count}개로 분류했습니다."
            if korean
            else (
                f"Service Health found {active_service_issues} active Azure outage event(s) "
                f"affecting {active_service_issue_resources} managed resource(s). It also found "
                f"{active_maintenance} active planned-maintenance event(s) affecting "
                f"{active_maintenance_resources} resource(s) and {active_advisories} active "
                f"advisory event(s) affecting {active_advisory_resources} resource(s). Resource "
                f"Health separately classified {platform_count} resource(s) as Azure platform "
                f"impact, {customer_count} as customer-initiated, and {unknown_count} as "
                "unclassified."
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
            f"Resource Health 조회 불가 범위 {resource_health_unavailable}개. "
            + (
                f"Service Health 조회 불가 {service_health_unavailable}개. "
                if service_health_requested
                else ""
            )
            + metric_summary
        )
        lines.append(f"근거: {source}, 관찰 시각 {observed_at}.")
        if truncated:
            lines.append("조회 한도에 도달했으므로 추가 리소스나 후보가 있을 수 있습니다.")
        if status == "partial":
            lines.append(
                "일부 Resource Health, Service Health 또는 메트릭 근거가 조회 불가이거나 "
                "미지원이므로 "
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
        f"Resource Health: {resource_health_unavailable} scope(s) unavailable. "
        + (
            f"Service Health: {service_health_unavailable} query set(s) unavailable. "
            if service_health_requested
            else ""
        )
        + metric_summary
    )
    lines.append(f"Evidence: {source}, observed {observed_at}.")
    if truncated:
        lines.append("The bounded query limit was reached; additional resources may exist.")
    if status == "partial":
        lines.append(
            "Some Resource Health, Service Health, or metric evidence was unavailable or "
            "unsupported, so "
            "complete normal operation was not confirmed."
        )
    return "\n".join(lines)


def _render_metric_comparison_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    comparisons = [
        item for item in result.get("metric_comparisons", []) if isinstance(item, Mapping)
    ]
    metric_family = str(result.get("metric_family") or "metric")
    anchor_at = str(result.get("anchor_at") or "unknown")
    if not comparisons:
        return (
            f"인시던트 {anchor_at} 전후의 {metric_family} 메트릭을 조회했지만 비교 가능한 "
            "point가 없습니다. 지원 대상, telemetry 수집 또는 두 window의 관측값이 필요합니다."
            if korean
            else (
                f"The {metric_family} metric was queried before and after incident anchor "
                f"{anchor_at}, but no comparable points were available. Supported targets, "
                "telemetry collection, and observations in both windows are required."
            )
        )
    lines = [
        (
            f"인시던트 anchor {anchor_at} 전후의 {metric_family} 메트릭을 같은 리소스에서 "
            f"비교했습니다. 비교 가능한 리소스: {len(comparisons)}개."
            if korean
            else (
                f"Compared {metric_family} metrics on the same resources before and after "
                f"incident anchor {anchor_at}. Comparable resources: {len(comparisons)}."
            )
        )
    ]
    for item in comparisons[:20]:
        name = str(item.get("resource_name") or "unknown")
        metric = str(item.get("metric") or metric_family)
        before = _finite_number(item.get("before_value"))
        after = _finite_number(item.get("after_value"))
        delta = _finite_number(item.get("delta"))
        if before is None or after is None or delta is None:
            continue
        lines.append(
            f"- {name}: {metric} 전 {before:g}, 후 {after:g}, 변화 {delta:+g}."
            if korean
            else f"- {name}: {metric} before {before:g}, after {after:g}, delta {delta:+g}."
        )
    lines.append(
        "이 비교는 시간적 동시성을 보여주며 원인을 단독으로 증명하지 않습니다."
        if korean
        else "This comparison shows temporal alignment and does not by itself prove cause."
    )
    return "\n".join(lines)


def _render_error_change_correlation_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    peak = result.get("peak_error_window")
    nearest = result.get("nearest_change")
    if not isinstance(peak, Mapping):
        return (
            "인시던트 전후의 오류율 window를 조회했지만 오류 요청 집계를 관찰하지 못했습니다. "
            "변경 activity가 있더라도 오류율과의 상관관계를 주장하지 않습니다."
            if korean
            else (
                "The error-rate window was queried around the incident, but no error-request "
                "aggregate was observed. Even if change activity exists, no correlation is claimed."
            )
        )
    peak_at = str(peak.get("time") or "unknown")
    error_count = _integer(peak.get("error_count"))
    request_count = _integer(peak.get("request_count"))
    if not isinstance(nearest, Mapping):
        return (
            f"오류가 가장 많은 window는 {peak_at}이며 오류 {error_count}건, 전체 요청 "
            f"{request_count}건입니다. 같은 bounded window에서 성공한 배포 또는 설정 변경은 "
            "관찰되지 않았습니다."
            if korean
            else (
                f"The peak error window was {peak_at} with {error_count} error(s) out of "
                f"{request_count} request(s). No successful deployment or configuration change "
                "was observed in the same bounded window."
            )
        )
    operation = str(nearest.get("operation") or "unknown")
    change_at = str(nearest.get("time") or "unknown")
    distance_seconds = _integer(nearest.get("distance_seconds"))
    return (
        f"오류가 가장 많은 window는 {peak_at}이며 오류 {error_count}건, 전체 요청 "
        f"{request_count}건입니다. 가장 가까운 성공 변경은 {change_at}의 {operation}이며 "
        f"시간 차이는 {distance_seconds}초입니다. 이는 시간적 연관이며 원인 증명이 아닙니다."
        if korean
        else (
            f"The peak error window was {peak_at} with {error_count} error(s) out of "
            f"{request_count} request(s). The nearest successful change was {operation} at "
            f"{change_at}, {distance_seconds} seconds away. This is temporal association, not "
            "proof of cause."
        )
    )


def _correlation_result(
    rows: Sequence[Mapping[str, Any]],
    *,
    anchor_at: str,
    observed_at: str,
    truncated: bool,
) -> dict[str, Any]:
    error_rows: list[dict[str, Any]] = []
    change_rows: list[dict[str, Any]] = []
    for row in rows[:100]:
        kind = str(row.get("evidence_kind") or "").casefold()
        occurred_at = row.get("TimeGenerated") or row.get("time_generated")
        if not isinstance(occurred_at, str) or not occurred_at:
            continue
        if kind == "error_rate":
            error_rows.append(
                {
                    "time": occurred_at,
                    "request_count": _integer(row.get("request_count")),
                    "error_count": _integer(row.get("error_count")),
                }
            )
        elif kind == "change":
            change_rows.append(
                {
                    "time": occurred_at,
                    "operation": _bounded_text(row.get("OperationNameValue")),
                    "resource_group": _bounded_text(row.get("ResourceGroup")),
                }
            )
    peak = max(error_rows, key=lambda item: item["error_count"], default=None)
    nearest = None
    if peak is not None:
        peak_time = _parse_aware_time(peak["time"])
        candidates = [
            (abs((_parse_aware_time(item["time"]) - peak_time).total_seconds()), item)
            for item in change_rows
        ]
        if candidates:
            distance, item = min(candidates, key=lambda candidate: candidate[0])
            nearest = {**item, "distance_seconds": round(distance)}
    return {
        "status": "partial" if truncated else "matched",
        "source": "azure-monitor-logs-activity-join",
        "observed_at": observed_at,
        "anchor_at": anchor_at,
        "peak_error_window": peak,
        "nearest_change": nearest,
        "error_window_count": len(error_rows),
        "change_count": len(change_rows),
        "truncated": truncated,
    }


def subscription_health_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    source = result.get("source")
    observed_at = result.get("observed_at")
    if not isinstance(source, str) or not isinstance(observed_at, str):
        return ()
    return (f"subscription-health:{source}@{observed_at}",)


def subscription_health_findings(
    evidence: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Return bounded findings after applying the typed resource filter."""

    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return []
    findings = [item for item in result.get("findings", []) if isinstance(item, Mapping)]
    return _filter_findings_by_requested_type(evidence, findings)[:20]


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


def _finding_lines(
    findings: list[Mapping[str, Any]],
    *,
    korean: bool,
    include_timeline: bool = False,
) -> list[str]:
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
            classification = _health_cause_classification(reason)
            observed_at = str(finding.get("observed_at") or "unknown")
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
                    f"resource group {resource_group}. "
                    + (
                        f"최초 관측 {observed_at}, 분류 {classification}. "
                        if include_timeline
                        else ""
                    )
                    + explanation
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
                    f"resource group {resource_group}. "
                    + (
                        f"First observed {observed_at}, classification {classification}. "
                        if include_timeline
                        else ""
                    )
                    + explanation
                )
            continue
        metric = finding.get("metric")
        value = finding.get("value")
        detail = f", {metric}={value}" if isinstance(metric, str) else ""
        lines.append(f"- {name}: {kind}, {status}{detail}")
    return lines


def _health_cause_classification(reason: str) -> str:
    normalized = reason.casefold().replace("_", " ").replace("-", " ")
    if "customer initiated" in normalized:
        return "customer-initiated"
    if "platform initiated" in normalized:
        return "platform-initiated"
    return "status-only"


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


def _render_health_coverage_answer(
    *,
    resource_health_unavailable: int,
    service_health_unavailable: int,
    metric_unavailable: int,
    unsupported: int,
    source: str,
    observed_at: str,
    status: str,
    truncated: bool,
    korean: bool,
) -> str:
    unavailable_total = (
        resource_health_unavailable + service_health_unavailable + metric_unavailable
    )
    if korean:
        headline = (
            "권한 또는 범위 때문에 조회 불가로 관찰된 상태 점검은 없습니다."
            if unavailable_total == 0
            else (
                f"조회 불가 상태 점검 범위는 {unavailable_total}개입니다. Provider 결과가 각 "
                "원인을 권한 또는 범위로 구분하지 않으므로 임의로 분류하지 않습니다."
            )
        )
        lines = [
            headline,
            f"- Resource Health 조회 불가 범위: {resource_health_unavailable}",
            f"- Service Health 조회 불가 query set: {service_health_unavailable}",
            f"- 메트릭 조회 불가: {metric_unavailable}",
            f"- 메트릭 미지원 리소스: {unsupported}",
            "Directory identity lookup과 CLI tooling failure는 이 상태 점검 coverage 밖입니다.",
            f"근거: {source}, 관찰 시각 {observed_at}.",
        ]
    else:
        headline = (
            "No health check was observed as unavailable because of authorization or scope."
            if unavailable_total == 0
            else (
                f"{unavailable_total} health-check scope(s) were unavailable. The provider "
                "result does not classify each cause as authorization or scope, so this answer "
                "does not guess between them."
            )
        )
        lines = [
            headline,
            f"- Resource Health unavailable scopes: {resource_health_unavailable}",
            f"- Service Health unavailable query sets: {service_health_unavailable}",
            f"- Metrics unavailable: {metric_unavailable}",
            f"- Metric-unsupported resources: {unsupported}",
            "Directory identity lookups and CLI tooling are outside this health-check coverage.",
            f"Evidence: {source}, observed {observed_at}.",
        ]
    if status == "partial":
        lines.append(
            "일부 상태 근거가 불완전하므로 전체 coverage를 확정하지 않았습니다."
            if korean
            else "Some health evidence was partial, so complete coverage was not confirmed."
        )
    if truncated:
        lines.append(
            "조회 한도에 도달해 추가 점검 범위가 있을 수 있습니다."
            if korean
            else "The query limit was reached; additional check scope may exist."
        )
    return "\n".join(lines)


def _service_health_event_lines(
    events: list[Mapping[str, Any]],
    *,
    korean: bool,
) -> list[str]:
    lines: list[str] = []
    for event in events[:20]:
        event_type = str(event.get("event_type") or "unknown")
        title = str(event.get("title") or "unknown")
        impacted = [
            item for item in event.get("impacted_resources", []) if isinstance(item, Mapping)
        ]
        names = ", ".join(str(item.get("name") or "unknown") for item in impacted[:10])
        resource_suffix = f": {names}" if names else ""
        if korean:
            lines.append(
                f"- Service Health {event_type}: {title}. 영향받는 관리형 리소스 "
                f"{len(impacted)}개{resource_suffix}"
            )
        else:
            lines.append(
                f"- Service Health {event_type}: {title}. {len(impacted)} impacted managed "
                f"resource(s){resource_suffix}"
            )
    return lines


def _status_query(prompt: str) -> dict[str, object]:
    language = default_inventory_query_language_resolver()
    platform_impact = language.has(language.registry.signals, "platform_health", prompt)
    health_history = language.has(language.registry.signals, "health_history", prompt)
    current_health_timeline = bool(_CURRENT_HEALTH_TIMELINE.search(prompt))
    health_coverage = bool(_HEALTH_COVERAGE.search(prompt))
    diagnostic_metric = _diagnostic_metric(prompt)
    metric_comparison = diagnostic_metric is not None and bool(
        _BEFORE_AFTER_COMPARISON.search(prompt)
    )
    error_change_correlation = bool(_ERROR_CHANGE_CORRELATION.search(prompt))
    pod_diagnosis = bool(_POD_DIAGNOSIS.search(prompt))
    capacity_diagnosis = bool(_CAPACITY_DIAGNOSIS.search(prompt))
    groups = (
        ()
        if platform_impact or health_history or current_health_timeline
        else inventory_query_status_groups(prompt)
    )
    if diagnostic_metric is not None:
        groups = tuple(group for group in groups if group.id != "unhealthy")
    requested_types = default_inventory_resource_type_resolver().resolve(prompt)
    return {
        "platform_impact": platform_impact,
        "health_history": health_history,
        "current_health_timeline": current_health_timeline,
        "health_coverage": health_coverage,
        "diagnostic_metric": diagnostic_metric,
        "metric_comparison": metric_comparison,
        "error_change_correlation": error_change_correlation,
        "pod_diagnosis": pod_diagnosis,
        "capacity_diagnosis": capacity_diagnosis,
        "lookback_seconds": (
            min(
                language.parse_window_seconds(prompt)
                or language.registry.default_activity_lookback_seconds,
                86_400,
            )
            if health_history
            else 3_600
        ),
        "requested_resource_types": list(requested_types),
        "requested_status_groups": [
            {"id": group.id, "values": list(group.values), "labels": dict(group.labels)}
            for group in groups
        ],
    }


def _render_health_history_answer(
    events: list[Mapping[str, Any]],
    *,
    lookback_seconds: int,
    source: str,
    observed_at: str,
    status: str,
    truncated: bool,
    korean: bool,
) -> str:
    ordered = sorted(events, key=lambda item: str(item.get("observed_at") or ""))
    classifications = {
        classification: sum(1 for event in ordered if event.get("classification") == classification)
        for classification in ("customer-initiated", "status-only", "platform-initiated")
    }
    if korean:
        lines = [
            f"지난 {lookback_seconds // 3_600}시간의 리소스 상태 이벤트 {len(ordered)}개입니다."
        ]
        lines.extend(
            f"- {event.get('observed_at', 'unknown')}: {event.get('resource_name', 'unknown')} - "
            f"{event.get('status', 'unknown')} ({event.get('classification', 'status-only')}, "
            f"{event.get('reason', 'unknown')})"
            for event in ordered[:64]
        )
        lines.append(
            "분류: "
            f"customer-initiated {classifications['customer-initiated']}건, "
            f"status-only {classifications['status-only']}건, "
            f"platform-initiated {classifications['platform-initiated']}건."
        )
        lines.append(f"근거: {source}, 관찰 시각 {observed_at}.")
        if truncated:
            lines.append("조회 한도에 도달했으므로 추가 이벤트가 있을 수 있습니다.")
        if status == "partial":
            lines.append("일부 상태 이벤트 근거를 조회할 수 없어 전체 이력을 확정하지 않았습니다.")
        return "\n".join(lines)
    lines = [
        f"Found {len(ordered)} resource health event(s) in the last "
        f"{lookback_seconds // 3_600} hours."
    ]
    lines.extend(
        f"- {event.get('observed_at', 'unknown')}: {event.get('resource_name', 'unknown')} - "
        f"{event.get('status', 'unknown')} ({event.get('classification', 'status-only')}, "
        f"{event.get('reason', 'unknown')})"
        for event in ordered[:64]
    )
    lines.append(
        "Classification: "
        f"customer-initiated {classifications['customer-initiated']}, "
        f"status-only {classifications['status-only']}, "
        f"platform-initiated {classifications['platform-initiated']}."
    )
    lines.append(f"Evidence: {source}, observed {observed_at}.")
    if truncated:
        lines.append("The bounded query limit was reached; additional events may exist.")
    if status == "partial":
        lines.append(
            "Some health-event evidence was unavailable, so the complete history was not confirmed."
        )
    return "\n".join(lines)


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


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _bounded_text(value: object) -> str:
    return " ".join(str(value or "unknown").split())[:128] or "unknown"


def _kql_text(value: str) -> str:
    if len(value) > 256 or any(character in value for character in "\r\n\x00"):
        raise ValueError("KQL scalar context is invalid")
    return value.replace("'", "''")


def _parse_aware_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("telemetry timestamp MUST be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("telemetry timestamp MUST be timezone-aware")
    return parsed.astimezone(UTC)


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
    "subscription_health_findings",
]
