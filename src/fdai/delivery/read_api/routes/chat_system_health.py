"""Deterministic bounded answers for server-owned system-health metrics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from fdai.delivery.read_api.read_model import ConsoleReadModel

_SYSTEM_HEALTH: Final = re.compile(
    r"\b(system|control plane|everything|overall)\b.{0,32}"
    r"\b(health|healthy|working|running|operating|status)\b"
    r"|\b(is|are)\s+(?:the\s+)?(?:system|control plane|everything)\s+"
    r"(?:working|running|operating)\b"
    "|전반적(?:인|으로)?.{0,20}(?:동작|작동|상태)"
    "|전체(?:적으로|\\s*시스템)?.{0,20}"
    "(?:잘\\s*(?:동작|작동)|정상\\s*(?:동작|작동)|상태)"
    "|시스템.{0,20}(?:건강|정상|상태|잘\\s*(?:동작|작동))",
    re.IGNORECASE,
)
_NON_HEALTH_CONTEXT: Final = re.compile(
    r"\b(?:policy|cost|budget|billing|price|pricing)\b|정책|비용|예산|청구|가격",
    re.IGNORECASE,
)


class ChatToolResolver(Protocol):
    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class SystemHealthChatTools:
    """Add broad health metrics ahead of the existing direct read tools."""

    read_model: ConsoleReadModel
    fallback: ChatToolResolver | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if _SYSTEM_HEALTH.search(prompt) and not _NON_HEALTH_CONTEXT.search(prompt):
            metrics = await self.read_model.dashboard_metrics()
            return {
                "tool": "get_system_health",
                "authority": "server_read_model",
                "result": metrics.to_dict(),
            }
        if self.fallback is not None:
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        return None


def render_system_health_answer(
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    """Render broad health questions without inferring beyond read-model KPIs."""

    evidence = view_context.get("_tool_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("tool") != "get_system_health":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None

    event_count = _non_negative_int(result.get("event_count"))
    hil_pending = _non_negative_int(result.get("hil_pending"))
    shadow_share = _ratio(result.get("shadow_share"))
    enforce_share = _ratio(result.get("enforce_share"))
    last_recorded_at = _optional_text(result.get("last_recorded_at"))
    if event_count is None or hil_pending is None:
        return None

    korean = _is_korean(locale)
    if event_count == 0:
        if korean:
            return (
                "현재 서버 read model의 감사 이벤트 수(event count)는 0건이고, "
                f"대기 중 승인 수(HIL pending)는 {hil_pending}건입니다. "
                "관측된 운영 표본이 없으므로 전체 시스템이 정상이라고 확정할 수는 "
                "없습니다. 이는 장애가 확인됐다는 뜻이 아니라 현재 근거가 부족하다는 뜻입니다."
            )
        return (
            "The server read model currently contains 0 audit events and "
            f"{hil_pending} pending approvals. With no observed operational sample, "
            "overall system health cannot be confirmed. This does not prove a failure; "
            "it means the current evidence is insufficient."
        )

    if korean:
        lines = [
            f"현재 서버 read model에서 감사 이벤트 수(event count) {event_count}건이 "
            f"관측됐고, 대기 중 승인 수(HIL pending)는 {hil_pending}건입니다."
        ]
        if shadow_share is not None and enforce_share is not None:
            lines.append(
                f"실행 모드 비율은 shadow {_percent(shadow_share)}, "
                f"enforce {_percent(enforce_share)}입니다."
            )
        if last_recorded_at is not None:
            lines.append(f"마지막 감사 기록 시각은 {last_recorded_at} 입니다.")
        lines.append(
            "이 수치는 현재 관측된 활동과 승인 대기 상태를 보여주지만, 모든 구성요소가 "
            "정상이라고 단정하는 전체 health probe는 아닙니다."
        )
        return " ".join(lines)

    lines = [
        f"The server read model currently shows {event_count} audit events and "
        f"{hil_pending} pending approvals."
    ]
    if shadow_share is not None and enforce_share is not None:
        lines.append(
            f"The execution-mode mix is {_percent(shadow_share)} shadow and "
            f"{_percent(enforce_share)} enforce."
        )
    if last_recorded_at is not None:
        lines.append(f"The latest audit record is {last_recorded_at}.")
    lines.append(
        "These metrics describe observed activity and approval backlog; they are not a "
        "complete health probe for every component."
    )
    return " ".join(lines)


def _non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _ratio(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if 0 <= numeric <= 1 else None


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _is_korean(locale: str | None) -> bool:
    return bool(locale and locale.lower().split("-", 1)[0].split("_", 1)[0] == "ko")


__all__ = ["SystemHealthChatTools", "render_system_health_answer"]
