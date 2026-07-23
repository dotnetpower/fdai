"""Deterministic principal-timezone current-time answers for Command Deck."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver
from fdai.shared.providers.user_context import UserPreferenceStore

_CURRENT_TIME: Final = re.compile(
    r"\b(?:what(?:'s|\s+is)\s+the\s+(?:current\s+)?time|what\s+time\s+is\s+it|"
    r"current\s+time|time\s+now)\b"
    r"|(?:지금|현재).{0,8}(?:몇\s*시|시간)|몇\s*시(?:야|예요|인가요|지)?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CurrentTimeChatTools:
    """Resolve current time from an injected clock and principal timezone."""

    preferences: UserPreferenceStore | None = None
    fallback: ChatToolResolver | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if not _CURRENT_TIME.search(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("current-time clock MUST be timezone-aware")
        record = (
            await self.preferences.get(principal_id=principal_id)
            if self.preferences is not None
            else None
        )
        timezone_name = record.timezone if record is not None and record.timezone else "UTC"
        localized = now.astimezone(ZoneInfo(timezone_name)).replace(microsecond=0)
        return {
            "tool": "get_current_time",
            "authority": "server_clock",
            "result": {
                "status": "matched",
                "timestamp": localized.isoformat(),
                "timezone": timezone_name,
                "timezone_source": (
                    "principal_preference" if timezone_name != "UTC" else "utc_fallback"
                ),
            },
        }


def render_current_time_answer(evidence: Mapping[str, Any], *, locale: str | None) -> str | None:
    """Render current-time evidence without model interpretation."""

    if evidence.get("tool") != "get_current_time":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "matched":
        return None
    timestamp = result.get("timestamp")
    timezone_name = result.get("timezone")
    if not isinstance(timestamp, str) or not isinstance(timezone_name, str):
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    display = parsed.strftime("%Y-%m-%d %H:%M:%S")
    if locale and locale.casefold().startswith("ko"):
        return f"현재 시각은 {display} ({timezone_name})입니다."
    return f"The current time is {display} ({timezone_name})."


def current_time_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Return one stable reference to the clock observation and timezone."""

    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    timestamp = result.get("timestamp")
    timezone_name = result.get("timezone")
    if not isinstance(timestamp, str) or not isinstance(timezone_name, str):
        return ()
    return (f"server-clock:{timestamp}:{timezone_name}",)


__all__ = [
    "CurrentTimeChatTools",
    "current_time_evidence_refs",
    "render_current_time_answer",
]
