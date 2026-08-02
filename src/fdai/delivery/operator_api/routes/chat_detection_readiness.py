"""Deterministic Command Deck access to agent-owned detection readiness."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from fdai.delivery.operator_api.routes.chat_system_health import ChatToolResolver
from fdai.delivery.operator_api.routes.detection_readiness import (
    DetectionReadinessReader,
    project_detection_readiness,
)

_TARGET: Final = re.compile(r"\b(?:aks|kubernetes|clusters?)\b|쿠버네티스|클러스터", re.IGNORECASE)
_READINESS: Final = re.compile(
    r"\b(?:detection|monitoring|telemetry)\s+readiness\b|"
    r"\breadiness\b|감지\s*준비|모니터링\s*준비|관측\s*준비",
    re.IGNORECASE,
)
_MUTATION: Final = re.compile(
    r"\b(?:enable|configure|create|delete|restart|fix|remediate)\b|"
    r"활성화|설정해|생성|삭제|재시작|수정|복구",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DetectionReadinessChatTools:
    reader: DetectionReadinessReader
    fallback: ChatToolResolver | None = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_detection_readiness(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        try:
            result = await project_detection_readiness(self.reader)
            status = "matched" if result["target_count"] else "empty"
            result = {"status": status, **result}
        except Exception as exc:  # noqa: BLE001 - read boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_detection_readiness",
            "authority": "server_detection_readiness",
            "result": result,
        }


def needs_detection_readiness(prompt: str) -> bool:
    return bool(
        _TARGET.search(prompt) and _READINESS.search(prompt) and not _MUTATION.search(prompt)
    )


def render_detection_readiness_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if evidence.get("tool") != "query_detection_readiness":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    status = result.get("status")
    if status == "unavailable":
        return (
            "에이전트가 소유한 AKS 감지 준비도 근거를 읽을 수 없어 상태를 확정하지 않았습니다."
            if korean
            else (
                "Agent-owned AKS detection readiness evidence is unavailable, "
                "so no status was confirmed."
            )
        )
    targets = result.get("targets")
    if not isinstance(targets, list):
        return None
    observed_at = str(result.get("observed_at") or "not observed")
    if not targets:
        return (
            "Muninn에 저장된 AKS 감지 준비도 snapshot이 없습니다."
            if korean
            else "Muninn has no stored AKS detection readiness snapshot."
        )
    lines = [
        (
            f"AKS 감지 준비도 대상 {len(targets)}개를 확인했습니다. 관찰 시각: {observed_at}."
            if korean
            else (
                f"Checked {len(targets)} AKS detection readiness target(s). "
                f"Observed: {observed_at}."
            )
        )
    ]
    for target in targets[:20]:
        if not isinstance(target, Mapping):
            continue
        resource = str(target.get("resource_ref") or "unknown")
        decision = str(target.get("decision") or "unknown")
        ceiling = str(target.get("authority_ceiling") or "unknown")
        missing = target.get("missing_dimensions")
        stale = target.get("stale_dimensions")
        missing_count = len(missing) if isinstance(missing, list) else 0
        stale_count = len(stale) if isinstance(stale, list) else 0
        if korean:
            lines.append(
                f"- {resource}: {decision}, 권한 상한 {ceiling}, "
                f"누락 {missing_count}, stale {stale_count}"
            )
        else:
            lines.append(
                f"- {resource}: {decision}, ceiling {ceiling}, "
                f"missing {missing_count}, stale {stale_count}"
            )
    lines.append("근거: Muninn StateSnapshot." if korean else "Evidence: Muninn StateSnapshot.")
    return "\n".join(lines)


def detection_readiness_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    observed_at = result.get("observed_at")
    if not isinstance(observed_at, str):
        return ()
    return (f"detection-readiness:muninn@{observed_at}",)


__all__ = [
    "DetectionReadinessChatTools",
    "detection_readiness_evidence_refs",
    "needs_detection_readiness",
    "render_detection_readiness_answer",
]
