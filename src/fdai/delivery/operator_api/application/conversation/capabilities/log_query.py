"""Bounded Command Deck adapter for explicit KQL reads."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.language import (
    default_inventory_query_language_resolver,
)
from fdai.delivery.operator_api.application.conversation.capabilities.system_health import (
    ChatToolResolver,
)
from fdai.shared.providers.observation import LogQueryProvider, ObservationError

_MAX_CHAT_ROWS = 100
_MAX_RENDERED_ROWS = 20
_MAX_RENDERED_COLUMNS = 8
_MAX_CELL_CHARS = 160
_FAILED_REQUESTS: Final = re.compile(
    r"\bfailed\s+requests?\b|\brequest\s+failures?\b|"
    r"(?:실패한?\s*요청|실패\s*요청|요청\s*실패)",
    re.IGNORECASE,
)
_FAILED_REQUESTS_QUERY: Final = (
    "AppRequests\n"
    '| where Success == false or ResultCode startswith "5"\n'
    "| summarize request_count=count(), first_seen=min(TimeGenerated), "
    "last_seen=max(TimeGenerated) by Name, ResultCode\n"
    "| top 20 by request_count desc"
)
_SIGNATURE_TIMELINE: Final = re.compile(
    r"\b(?:error|signature)\b.{0,64}\b(?:first|latest|recently|occur|appear)\b|"
    r"\b(?:first|latest|recently|occur|appear)\b.{0,64}\b(?:error|signature)\b|"
    r"(?:오류|에러|시그니처).{0,48}(?:첫|처음|최초|마지막|최신)",
    re.IGNORECASE,
)
_RELATED_LOGS: Final = re.compile(r"\brelated\s+logs?\b|관련\s*로그", re.IGNORECASE)
_REPRESENTATIVE_LOGS: Final = re.compile(
    r"\b(?:logs?).{0,40}(?:examples?|samples?)\b|"
    r"\b(?:representative|examples?|samples?).{0,40}(?:logs?)\b|"
    r"(?:오류|에러)?.{0,16}로그.{0,16}(?:예시|샘플)",
    re.IGNORECASE,
)
_REPRESENTATIVE_LOGS_QUERY: Final = (
    "union isfuzzy=true withsource=source_table AppExceptions, AppTraces, ContainerLogV2\n"
    "| extend log_message=coalesce(OuterMessage, Message, LogMessage)\n"
    "| extend severity=coalesce(tostring(SeverityLevel), LogLevel)\n"
    '| where source_table == "AppExceptions" or toint(SeverityLevel) >= 3 '
    'or LogLevel in~ ("error", "critical")\n'
    "| project TimeGenerated, source_table, severity, log_message\n"
    "| order by TimeGenerated desc"
)
_TRACE_WATERFALL: Final = re.compile(
    r"\b(?:distributed\s+trace|trace).{0,48}"
    r"(?:slowest|longest|highest[-\s]latency|bottleneck|span)\b|"
    r"\b(?:slowest|longest|highest[-\s]latency|bottleneck|span).{0,48}"
    r"(?:distributed\s+trace|trace)\b|"
    r"분산\s*(?:추적|trace).{0,32}(?:느린|병목|구간|span)|"
    r"(?:느린|병목|최장\s*지연).{0,32}분산\s*(?:추적|trace)|"
    r"(?:가장\s*)?느린\s*추적.{0,32}(?:병목|span)",
    re.IGNORECASE,
)
_DEPENDENCY_LATENCY: Final = re.compile(
    r"\b(?:dependency|dependent\s+service|downstream(?:\s+call)?).{0,48}"
    r"(?:latency|slow|delay|source|contribut)\w*\b|"
    r"\b(?:latency|slow|delay).{0,48}"
    r"(?:dependency|dependent\s+service|downstream(?:\s+call)?)\b|"
    r"(?:종속\s*서비스|종속성(?:\s*경로)?|다운스트림|downstream\s*서비스).{0,40}"
    r"(?:응답\s*(?:지연|시간\s*증가)|느려|기여|지연)|"
    r"(?:응답\s*(?:지연|시간\s*증가)|느려|지연|기여).{0,40}"
    r"(?:종속\s*서비스|종속성(?:\s*경로)?|다운스트림|downstream\s*서비스)",
    re.IGNORECASE,
)
_DATABASE_SLOW_CALLS: Final = re.compile(
    r"\b(?:database|db|sql).{0,56}(?:query|queries|call|cpu|slow)\b|"
    r"\b(?:slow|cpu).{0,56}(?:database|db|sql).{0,24}(?:query|queries|calls?)\b|"
    r"\bquery\s+evidence\b.{0,56}\bcpu\s+spike\b|"
    r"(?:데이터베이스|DB|SQL).{0,40}(?:CPU|느린\s*쿼리|쿼리)",
    re.IGNORECASE,
)
_TRACE_WATERFALL_QUERY: Final = (
    "union "
    "(AppRequests | project TimeGenerated, OperationId, SpanId=Id, ParentId, "
    'SpanType="request", Name, Target="", DurationMs), '
    "(AppDependencies | project TimeGenerated, OperationId, SpanId=Id, ParentId, "
    'SpanType="dependency", Name, Target, DurationMs)\n'
    "| summarize trace_duration_ms=sum(DurationMs), "
    "arg_max(DurationMs, TimeGenerated, SpanId, ParentId, SpanType, Name, Target) "
    "by OperationId\n"
    "| top 1 by trace_duration_ms desc"
)
_DEPENDENCY_LATENCY_QUERY: Final = (
    "AppDependencies\n"
    "| summarize call_count=count(), failed_calls=countif(Success == false), "
    "p95_duration_ms=percentile(DurationMs, 95), total_duration_ms=sum(DurationMs) "
    "by Target, DependencyType\n"
    "| top 20 by total_duration_ms desc"
)
_POD_DIAGNOSIS: Final = re.compile(
    r"\b(?:this\s+)?pod\b.{0,48}\b(?:restart|restarting|throttl|reason|cause)\w*\b|"
    r"(?:이\s*)?(?:파드|pod).{0,40}(?:재시작|throttl|이유|원인)",
    re.IGNORECASE,
)
_CAPACITY_DIAGNOSIS: Final = re.compile(
    r"\bcapacity\b.{0,64}\b(?:traffic|load|demand|trend|handle|enough|headroom)\b|"
    r"\b(?:traffic|load|demand|trend|headroom)\b.{0,64}"
    r"\b(?:capacity|handle|enough|headroom)\b|"
    r"\bheadroom\b.{0,48}\b(?:demand|load|traffic)\s+trend\b|"
    r"(?:용량|capacity).{0,48}(?:트래픽|부하|증가|감당|충분)",
    re.IGNORECASE,
)
_BOUNDED_ERROR_QUERY: Final = re.compile(
    r"\b(?:run|execute).{0,40}(?:bounded|read-only|safe).{0,32}(?:query|kql)"
    r".{0,32}errors?\b|"
    r"\b(?:run|execute).{0,40}(?:query|kql).{0,32}errors?\b|"
    r"\bquery\b.{0,32}\berrors?\b.{0,64}\b(?:15[- ]minute|no\s+write)\b|"
    r"(?:오류|에러).{0,32}(?:안전한\s*)?(?:KQL|로그\s*쿼리).{0,20}(?:실행|찾)",
    re.IGNORECASE,
)
_CHAT_WINDOW: Final = re.compile(
    r"(?P<value>[1-9][0-9]{0,2})\s*-?\s*(?P<unit>minutes?|mins?|hours?|hrs?|분|시간)",
    re.IGNORECASE,
)
_REDACTION_PATTERNS: Final = (
    re.compile(r"(?i)\b(?:password|passwd|token|api[_-]?key|secret)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/-]+=*"),
    re.compile(r"(?i)/subscriptions/[0-9a-f-]+(?:/[^\s\"'<>]+)+"),
    re.compile(
        r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
    ),
    re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}\b"),
    re.compile(r"(?i)https?://[^\s\"'<>]+"),
    re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
)


@dataclass(frozen=True, slots=True)
class LogQueryChatTools:
    """Resolve explicit ``query_log`` commands through a real log provider."""

    provider: LogQueryProvider | None
    fallback: ChatToolResolver | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        head = prompt.lstrip().split(maxsplit=1)
        if not head or head[0] != "query_log":
            if _FAILED_REQUESTS.search(prompt):
                return await self._query(
                    query=_FAILED_REQUESTS_QUERY,
                    window=_window_from_prompt(prompt),
                    max_rows=20,
                    intent="failed_requests",
                )
            if _BOUNDED_ERROR_QUERY.search(prompt):
                return await self._query(
                    query=_REPRESENTATIVE_LOGS_QUERY,
                    window=_window_from_prompt(prompt),
                    max_rows=20,
                    intent="bounded_error_query",
                )
            if _SIGNATURE_TIMELINE.search(prompt) or _RELATED_LOGS.search(prompt):
                return _clarification_evidence("exact_error_signature_required")
            if _REPRESENTATIVE_LOGS.search(prompt):
                return await self._query(
                    query=_REPRESENTATIVE_LOGS_QUERY,
                    window=_window_from_prompt(prompt),
                    max_rows=20,
                    intent="representative_logs",
                )
            if _TRACE_WATERFALL.search(prompt):
                return await self._query(
                    query=_TRACE_WATERFALL_QUERY,
                    window=_window_from_prompt(prompt, default_seconds=3_600),
                    max_rows=20,
                    intent="trace_waterfall",
                )
            if _DEPENDENCY_LATENCY.search(prompt):
                return await self._query(
                    query=_DEPENDENCY_LATENCY_QUERY,
                    window=_window_from_prompt(prompt, default_seconds=3_600),
                    max_rows=20,
                    intent="dependency_latency",
                )
            if _DATABASE_SLOW_CALLS.search(prompt):
                return _clarification_evidence("exact_resource_selector_required")
            return await self._fallback(prompt, principal_id=principal_id)

        try:
            arguments = _parse_arguments(head[1] if len(head) == 2 else "")
        except ValueError as exc:
            return _error_evidence("invalid_log_query_arguments", str(exc))

        return await self._query(
            query=arguments["query"],
            window=arguments["window"],
            max_rows=arguments["max_rows"],
        )

    async def resolve_with_context(
        self,
        prompt: str,
        *,
        principal_id: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not needs_log_query_context(prompt):
            return await self.resolve(prompt, principal_id=principal_id)
        resource_context = context.get("resource_context") if context is not None else None
        resource_name = (
            resource_context.get("name") if isinstance(resource_context, Mapping) else None
        )
        if not isinstance(resource_name, str) or not resource_name:
            return _clarification_evidence("exact_resource_selector_required")
        name = _kql_literal(resource_name)
        window = _window_from_prompt(prompt, default_seconds=3_600)
        if _DATABASE_SLOW_CALLS.search(prompt):
            query = (
                "union "
                "(AzureMetrics "
                f"| where Resource has '{name}' and MetricName has 'cpu' "
                "| project TimeGenerated, evidence_kind='cpu_metric', MetricName, "
                "MetricValue=Maximum), "
                "(AppDependencies "
                f"| where (Target has '{name}' or Name has '{name}') "
                "and DependencyType has_any ('SQL', 'PostgreSQL', 'MySQL') "
                "| project TimeGenerated, evidence_kind='database_call', Target, "
                "DependencyType, Name, DurationMs, Success, ResultCode) "
                "| order by TimeGenerated asc"
            )
            intent = "database_cpu_join"
        elif _POD_DIAGNOSIS.search(prompt):
            query = (
                "union "
                "(KubePodInventory "
                f"| where Name =~ '{name}' "
                "| project TimeGenerated, evidence_kind='pod_state', Name, PodStatus, "
                "ContainerRestartCount, ContainerStatusReason), "
                "(Perf "
                f"| where InstanceName has '{name}' "
                "and CounterName has_any ('cpuUsageNanoCores', 'cpuLimitNanoCores', "
                "'memoryRssBytes', 'memoryLimitBytes') "
                "| project TimeGenerated, evidence_kind='pod_resource', CounterName, "
                "CounterValue) | order by TimeGenerated asc"
            )
            intent = "pod_diagnosis"
        else:
            query = (
                "union "
                "(InsightsMetrics "
                f"| where Tags has '{name}' and Name has_any ('cpuUsageNanoCores', "
                "'memoryRssBytes', 'requests', 'limits') "
                "| project TimeGenerated, evidence_kind='load', Name, Val), "
                "(KubeNodeInventory "
                "| project TimeGenerated, evidence_kind='limit', Computer, "
                "AllocatableCpuCore, AllocatableMemoryBytes) | order by TimeGenerated asc"
            )
            intent = "capacity_trend"
        return await self._query(query=query, window=window, max_rows=100, intent=intent)

    async def _query(
        self,
        *,
        query: str,
        window: str,
        max_rows: int,
        intent: str | None = None,
    ) -> dict[str, Any]:
        if self.provider is None:
            return _error_evidence(
                "log_query_not_configured",
                "Azure Monitor Logs is not configured for this deployment",
                status="unavailable",
            )
        try:
            result = await self.provider.query_log(
                query=query,
                window=window,
                max_rows=max_rows,
            )
        except ObservationError as exc:
            return _error_evidence("log_query_unavailable", str(exc), status="unavailable")

        rows = [_bounded_row(row) for row in result.rows]
        return {
            "tool": "query_log",
            "authority": "server_log_query",
            "status": "ok",
            "result": {
                "status": "matched" if rows else "empty",
                "source": "azure_monitor_logs",
                "query_digest": _query_digest(query),
                "window": window,
                "rows": rows,
                "row_count": len(rows),
                "truncated": result.truncated,
                "returned_records": result.scanned_records,
                **({"intent": intent} if intent is not None else {}),
            },
        }

    async def _fallback(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if self.fallback is None:
            return None
        return await self.fallback.resolve(prompt, principal_id=principal_id)


def needs_log_query(prompt: str) -> bool:
    """Return whether the prompt requires the server-owned log authority."""

    head = prompt.lstrip().split(maxsplit=1)
    return bool(
        (head and head[0] == "query_log")
        or _FAILED_REQUESTS.search(prompt)
        or _SIGNATURE_TIMELINE.search(prompt)
        or _RELATED_LOGS.search(prompt)
        or _REPRESENTATIVE_LOGS.search(prompt)
        or _TRACE_WATERFALL.search(prompt)
        or _DEPENDENCY_LATENCY.search(prompt)
        or _DATABASE_SLOW_CALLS.search(prompt)
        or _BOUNDED_ERROR_QUERY.search(prompt)
    )


def needs_log_query_context(prompt: str) -> bool:
    return bool(
        _DATABASE_SLOW_CALLS.search(prompt)
        or _POD_DIAGNOSIS.search(prompt)
        or _CAPACITY_DIAGNOSIS.search(prompt)
    )


def render_log_query_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    """Render KQL rows without allowing row text to steer answer generation."""

    if evidence.get("tool") != "query_log":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = _is_korean(locale)
    status = result.get("status")
    if status == "clarification":
        reason = result.get("reason")
        if reason == "exact_resource_selector_required":
            return (
                "정확한 resource 또는 pod를 선택한 뒤 다시 요청해 주세요."
                if korean
                else "Select an exact resource or pod before retrying this diagnostic."
            )
        if korean:
            return (
                "조회할 정확한 오류 시그니처를 지정해 주세요. 시그니처가 없으면 최초와 "
                "최근 발생 시점 또는 관련 로그를 안전하게 선택할 수 없습니다."
            )
        return (
            "Specify the exact error signature to query. Without it, the first and latest "
            "occurrences or related logs cannot be selected safely."
        )
    if status in {"invalid", "unavailable"}:
        error = result.get("error")
        message = error.get("message") if isinstance(error, Mapping) else None
        detail = str(message) if isinstance(message, str) and message else "unknown error"
        if korean:
            return f"KQL 질의를 실행하거나 검증하지 못했습니다. 상태: {detail}"
        return f"The KQL query was not executed or verified. Status: {detail}"

    rows = result.get("rows")
    if not isinstance(rows, list):
        return None
    window = str(result.get("window") or "unknown")
    truncated = result.get("truncated") is True
    if not rows:
        if result.get("intent") == "failed_requests":
            if korean:
                return (
                    f"Azure Monitor Logs에서 {window} 범위의 실패 요청을 작업과 결과 코드별로 "
                    "조회했으며 일치하는 행은 0건입니다. 이 그룹화만으로 근본 원인을 "
                    "증명할 수는 없습니다. 근거: azure_monitor_logs"
                )
            return (
                f"The failed-request query ran against Azure Monitor Logs for {window}, grouped "
                "by operation and result code, and returned 0 rows. This grouping is not "
                "root-cause proof. Evidence: azure_monitor_logs"
            )
        if result.get("intent") == "representative_logs":
            if korean:
                return (
                    f"Azure Monitor Logs에서 {window} 범위의 대표 오류 로그를 조회하고 "
                    "민감한 텍스트 패턴을 제거했으며 일치하는 행은 0건입니다. "
                    "근거: azure_monitor_logs"
                )
            return (
                f"The representative-error query ran against Azure Monitor Logs for {window}, "
                "with sensitive text patterns redacted, and returned 0 rows. "
                "Evidence: azure_monitor_logs"
            )
        if korean:
            return (
                f"Azure Monitor Logs에서 {window} 범위의 bounded KQL을 실행했으며 "
                "일치하는 행은 0건입니다. 근거: azure_monitor_logs"
            )
        return (
            f"The bounded KQL query ran against Azure Monitor Logs for {window} and "
            "returned 0 rows. Evidence: azure_monitor_logs"
        )

    rendered = _render_rows(rows)
    shown = min(len(rows), _MAX_RENDERED_ROWS)
    diagnostic_limits = {
        "trace_waterfall": (
            "분산 추적 병목 진단(trace-waterfall)은 가장 느린 관측 trace의 span을 순위화하지만 "
            "근본 원인을 증명하지는 않습니다.",
            "The trace-waterfall diagnostic ranks spans in the slowest observed trace but is not "
            "root-cause proof.",
        ),
        "dependency_latency": (
            "종속성 지연 진단(dependency-latency)은 관측된 누적 지연을 순위화하지만 인과적 "
            "기여를 증명하지는 않습니다.",
            "The dependency-latency diagnostic ranks observed aggregate latency but does not "
            "prove causal contribution.",
        ),
        "database_slow_calls": (
            "느린 데이터베이스 호출 진단(database-slow-calls)은 dependency telemetry를 "
            "보여주지만 CPU 상승의 원인을 증명하지는 않습니다.",
            "The database-slow-calls diagnostic shows dependency telemetry but does not prove "
            "what caused a CPU increase.",
        ),
        "database_cpu_join": (
            "데이터베이스 CPU와 느린 dependency call을 같은 window에 표시하지만 시간적 정렬만으로 "
            "CPU 상승 원인을 증명하지는 않습니다.",
            "The diagnostic aligns database CPU and slow dependency calls in one window, but "
            "that temporal alignment does not prove what caused the CPU increase.",
        ),
        "pod_diagnosis": (
            "Pod restart 상태와 관측 resource 사용량을 함께 표시합니다. 누락된 event 또는 limit는 "
            "원인으로 추정하지 않습니다.",
            "The diagnostic shows pod restart state and observed resource use together. Missing "
            "events or limits are not inferred as a cause.",
        ),
        "capacity_trend": (
            "관측 load와 수집된 resource limit를 함께 표시합니다. Limit row가 없으면 현재 용량이 "
            "충분하다고 확정할 수 없습니다.",
            "The diagnostic shows observed load with collected resource limits. Without limit "
            "rows, current capacity cannot be confirmed as sufficient.",
        ),
        "bounded_error_query": (
            "bounded-error-query는 server-owned read-only template을 실행하며 반환된 오류 행만 "
            "보여줍니다.",
            "The bounded-error-query runs a server-owned read-only template and shows only the "
            "returned error rows.",
        ),
    }
    intent = result.get("intent")
    if isinstance(intent, str) and intent in diagnostic_limits:
        limitation = diagnostic_limits[intent][0 if korean else 1]
        prefix = (
            f"Azure Monitor Logs에서 {window} 범위의 진단 행 {len(rows)}개를 반환했고, "
            f"아래에 {shown}개를 표시합니다."
            if korean
            else f"The diagnostic query ran against Azure Monitor Logs for {window}, returned "
            f"{len(rows)} rows, and shows {shown} below."
        )
        evidence_label = "근거" if korean else "Evidence"
        return f"{prefix} {limitation}\n\n{rendered}\n\n{evidence_label}: azure_monitor_logs"
    if result.get("intent") == "failed_requests":
        if korean:
            return (
                f"Azure Monitor Logs에서 {window} 범위의 실패 요청을 작업과 결과 코드별로 "
                f"그룹화해 {len(rows)}개 행을 반환했고, 아래에 {shown}개를 표시합니다. "
                "이 그룹화만으로 근본 원인을 증명할 수는 없습니다."
                f"\n\n{rendered}\n\n근거: azure_monitor_logs"
            )
        return (
            f"The failed-request query ran against Azure Monitor Logs for {window}, grouped by "
            f"operation and result code, returned {len(rows)} rows, and shows {shown} below. "
            "This grouping is not root-cause proof."
            f"\n\n{rendered}\n\nEvidence: azure_monitor_logs"
        )
    if result.get("intent") == "representative_logs":
        if korean:
            return (
                f"Azure Monitor Logs에서 {window} 범위의 대표 오류 로그 {len(rows)}개 행을 "
                f"반환했고, 민감한 텍스트 패턴을 제거한 {shown}개를 아래에 표시합니다."
                f"\n\n{rendered}\n\n근거: azure_monitor_logs"
            )
        return (
            f"The representative-error query ran against Azure Monitor Logs for {window}, "
            f"returned {len(rows)} rows, and shows {shown} below after sensitive text patterns "
            f"were redacted.\n\n{rendered}\n\nEvidence: azure_monitor_logs"
        )
    if korean:
        prefix = (
            f"Azure Monitor Logs에서 {window} 범위의 bounded KQL을 실행해 "
            f"{len(rows)}개 행을 반환했고, 아래에 {shown}개를 표시합니다."
        )
        suffix = " 결과가 잘렸습니다." if truncated else ""
        return f"{prefix}{suffix}\n\n{rendered}\n\n근거: azure_monitor_logs"
    prefix = (
        f"The bounded KQL query ran against Azure Monitor Logs for {window}, returned "
        f"{len(rows)} rows, and shows {shown} below."
    )
    suffix = " The result was truncated." if truncated else ""
    return f"{prefix}{suffix}\n\n{rendered}\n\nEvidence: azure_monitor_logs"


def log_query_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    digest = result.get("query_digest")
    window = result.get("window")
    if not isinstance(digest, str) or not isinstance(window, str):
        return ()
    return (f"azure-monitor-logs:kql:{digest}@{window}",)


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"query_log arguments are malformed: {exc}") from exc
    values: dict[str, str] = {}
    for token in tokens:
        key, separator, value = token.partition("=")
        if not separator or key not in {"query", "window", "max_rows"}:
            raise ValueError(
                "query_log requires query=<KQL> window=<ISO duration> and optional max_rows=<N>"
            )
        if key in values:
            raise ValueError(f"query_log argument {key!r} was supplied more than once")
        values[key] = value
    query = values.get("query", "").strip()
    window = values.get("window", "").strip()
    if not query or not window:
        raise ValueError("query_log requires non-empty query and window arguments")
    try:
        max_rows = int(values.get("max_rows", "100"))
    except ValueError as exc:
        raise ValueError("query_log max_rows MUST be an integer") from exc
    if max_rows < 1 or max_rows > _MAX_CHAT_ROWS:
        raise ValueError(f"query_log max_rows MUST be between 1 and {_MAX_CHAT_ROWS}")
    return {"query": query, "window": window, "max_rows": max_rows}


def _window_from_prompt(prompt: str, *, default_seconds: int = 1_800) -> str:
    parsed = default_inventory_query_language_resolver().parse_window_seconds(prompt)
    if parsed is None and (match := _CHAT_WINDOW.search(prompt)) is not None:
        hour_units = {"hour", "hours", "hr", "hrs", "시간"}
        multiplier = 3_600 if match.group("unit").casefold() in hour_units else 60
        parsed = int(match.group("value")) * multiplier
    seconds = min(parsed or default_seconds, 86_400)
    if seconds % 3_600 == 0:
        return f"PT{seconds // 3_600}H"
    if seconds % 60 == 0:
        return f"PT{seconds // 60}M"
    return f"PT{seconds}S"


def _bounded_row(row: Mapping[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for index, (key, value) in enumerate(row.items()):
        if index >= _MAX_RENDERED_COLUMNS:
            break
        bounded[str(key)[:80]] = _bounded_value(value)
    return bounded


def _bounded_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_text(value)[:_MAX_CELL_CHARS]
    if isinstance(value, (Mapping, list, tuple)):
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        return _redact_text(serialized)[:_MAX_CELL_CHARS]
    return _redact_text(str(value))[:_MAX_CELL_CHARS]


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _kql_literal(value: str) -> str:
    if not 0 < len(value) <= 256 or any(character in value for character in "\r\n\x00"):
        raise ValueError("diagnostic resource selector is invalid")
    return value.replace("'", "''")


def _render_rows(rows: list[Any]) -> str:
    mappings = [row for row in rows[:_MAX_RENDERED_ROWS] if isinstance(row, Mapping)]
    columns = tuple(dict.fromkeys(str(key) for row in mappings for key in row))[
        :_MAX_RENDERED_COLUMNS
    ]
    if not columns:
        return "(rows contain no displayable columns)"
    header = "| " + " | ".join(_markdown_cell(column) for column in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |"
        for row in mappings
    ]
    return "\n".join((header, divider, *body))


def _markdown_cell(value: Any) -> str:
    text = "null" if value is None else str(value)
    return text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")


def _query_digest(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:16]


def _error_evidence(code: str, message: str, *, status: str = "invalid") -> dict[str, Any]:
    return {
        "tool": "query_log",
        "authority": "server_log_query",
        "status": "error" if status == "invalid" else "abstain",
        "result": {
            "status": status,
            "error": {"code": code, "message": message[:300]},
        },
    }


def _clarification_evidence(reason: str) -> dict[str, Any]:
    return {
        "tool": "query_log",
        "authority": "server_log_query",
        "status": "abstain",
        "result": {"status": "clarification", "reason": reason},
    }


def _is_korean(locale: str | None) -> bool:
    return bool(locale and locale.lower().split("-", 1)[0].split("_", 1)[0] == "ko")


__all__ = [
    "LogQueryChatTools",
    "log_query_evidence_refs",
    "needs_log_query",
    "render_log_query_answer",
]
