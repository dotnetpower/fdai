"""Deterministic subscription health evidence for Command Deck."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver

_SCOPE: Final = re.compile(r"\b(?:azure\s+)?subscriptions?\b|구독", re.IGNORECASE)
_HEALTH: Final = re.compile(
    r"\b(?:health|status|state|anomal(?:y|ies)|issues?|degraded|unavailable|check|inspect)\b"
    r"|상태|이상|장애|문제|점검|확인|비정상",
    re.IGNORECASE,
)
_MUTATION: Final = re.compile(
    r"\b(?:create|delete|restart|scale|update|change|remediate|fix)\b"
    r"|생성|삭제|재시작|스케일|변경|수정|복구",
    re.IGNORECASE,
)


class SubscriptionHealthProvider(Protocol):
    async def __call__(
        self,
        lookback_seconds: int,
        *,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SubscriptionHealthChatTools:
    provider: SubscriptionHealthProvider
    fallback: ChatToolResolver | None = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_subscription_health(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        try:
            result = dict(await self.provider(3_600))
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_subscription_health",
            "authority": "server_subscription_health",
            "result": result,
        }

    async def resolve_with_progress(
        self,
        prompt: str,
        *,
        principal_id: str,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> dict[str, Any] | None:
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
            result = dict(await self.provider(3_600, progress_observer=observe))
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
            "result": result,
        }


def needs_subscription_health(prompt: str) -> bool:
    return bool(_SCOPE.search(prompt) and _HEALTH.search(prompt) and not _MUTATION.search(prompt))


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
    metric_checked = _integer(result.get("metric_checked"))
    metric_unavailable = _integer(result.get("metric_unavailable"))
    unsupported = _integer(result.get("unsupported_metric_resources"))
    findings = [item for item in result.get("findings", []) if isinstance(item, Mapping)]
    source = str(result.get("source") or "Azure read providers")
    observed_at = str(result.get("observed_at") or "unknown")
    truncated = bool(result.get("truncated"))
    if korean:
        lines = [
            f"허용된 Azure 범위에서 리소스 {resource_count}개를 확인했고 "
            f"상태 이상 후보 {len(findings)}개를 찾았습니다."
        ]
        lines.extend(_finding_lines(findings, korean=True))
        lines.append(
            f"메트릭 확인: {metric_checked}개, 조회 불가 {metric_unavailable}개, "
            f"미지원 {unsupported}개."
        )
        lines.append(f"근거: {source}, 관찰 시각 {observed_at}.")
        if truncated:
            lines.append("조회 한도에 도달했으므로 추가 리소스나 후보가 있을 수 있습니다.")
        if status == "partial":
            lines.append("일부 메트릭을 조회하지 못했으므로 전체 정상 상태를 확정하지 않았습니다.")
        return "\n".join(lines)
    lines = [
        f"Checked {resource_count} resources in the allowed Azure scope and found "
        f"{len(findings)} health candidate(s)."
    ]
    lines.extend(_finding_lines(findings, korean=False))
    lines.append(
        f"Metrics: {metric_checked} checked, {metric_unavailable} unavailable, "
        f"{unsupported} unsupported."
    )
    lines.append(f"Evidence: {source}, observed {observed_at}.")
    if truncated:
        lines.append("The bounded query limit was reached; additional resources may exist.")
    if status == "partial":
        lines.append(
            "Some metrics were unavailable, so complete normal operation was not confirmed."
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
        metric = finding.get("metric")
        value = finding.get("value")
        detail = f", {metric}={value}" if isinstance(metric, str) else ""
        lines.append(f"- {name}: {kind}, {status}{detail}")
    return lines


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


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
    "needs_subscription_health",
    "render_subscription_health_answer",
    "subscription_health_evidence_refs",
]
