"""Pure metric comparison and error-change correlation helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Final

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


def diagnostic_metric(prompt: str) -> str | None:
    """Return the supported metric family requested by a diagnostic prompt."""

    if _CPU_DIAGNOSIS.search(prompt):
        return "cpu"
    if _MEMORY_DIAGNOSIS.search(prompt):
        return "memory"
    return None


def is_before_after_comparison_prompt(prompt: str) -> bool:
    """Return whether the prompt requests an incident-window metric comparison."""

    return bool(_BEFORE_AFTER_COMPARISON.search(prompt))


def is_error_change_correlation_prompt(prompt: str) -> bool:
    """Return whether the prompt requests error-rate and change correlation."""

    return bool(_ERROR_CHANGE_CORRELATION.search(prompt))


def render_metric_change_answer(
    query: object,
    result: Mapping[str, Any],
    *,
    korean: bool,
) -> str | None:
    """Render a metric comparison or error-change correlation result when requested."""

    metric_comparison = isinstance(query, Mapping) and query.get("metric_comparison") is True
    error_change_correlation = (
        isinstance(query, Mapping) and query.get("error_change_correlation") is True
    )
    if not metric_comparison and not error_change_correlation:
        return None
    if result.get("status") not in {"matched", "partial"}:
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
        return None
    if metric_comparison:
        return _render_metric_comparison_answer(result, korean=korean)
    return _render_error_change_correlation_answer(result, korean=korean)


def correlation_result(
    rows: Sequence[Mapping[str, Any]],
    *,
    anchor_at: str,
    observed_at: str,
    truncated: bool,
) -> dict[str, Any]:
    """Normalize bounded metric and activity rows into temporal correlation evidence."""

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


def kql_text(value: str) -> str:
    """Escape one bounded server-selected scalar for a KQL string literal."""

    if len(value) > 256 or any(character in value for character in "\r\n\x00"):
        raise ValueError("KQL scalar context is invalid")
    return value.replace("'", "''")


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


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _bounded_text(value: object) -> str:
    return " ".join(str(value or "unknown").split())[:128] or "unknown"


def _parse_aware_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("telemetry timestamp MUST be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("telemetry timestamp MUST be timezone-aware")
    return parsed.astimezone(UTC)
