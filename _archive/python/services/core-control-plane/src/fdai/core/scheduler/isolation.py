"""Default-deny enforcement for scheduled session isolation profiles."""

from __future__ import annotations

from fdai.core.scheduler.models import ScheduledRunIsolationProfile


class ScheduledRunIsolationError(ValueError):
    """A scheduled runtime request exceeded its server-owned profile."""


class ScheduledRunIsolationGuard:
    def __init__(self, profile: ScheduledRunIsolationProfile) -> None:
        self._profile = profile

    def authorize(
        self,
        *,
        context_chars: int,
        elapsed_seconds: float,
        tool_id: str | None = None,
        prior_tool_calls: int = 0,
    ) -> None:
        if context_chars < 0 or context_chars > self._profile.max_context_chars:
            raise ScheduledRunIsolationError("scheduled context exceeds its isolation profile")
        if elapsed_seconds < 0 or elapsed_seconds > self._profile.max_session_seconds:
            raise ScheduledRunIsolationError("scheduled session exceeds its isolation profile")
        if tool_id is None:
            return
        if tool_id not in self._profile.allowed_tool_ids:
            raise ScheduledRunIsolationError("scheduled tool is outside its isolation profile")
        if prior_tool_calls < 0 or prior_tool_calls >= self._profile.max_tool_calls:
            raise ScheduledRunIsolationError("scheduled tool-call cap is reached")


def isolation_payload(profile: ScheduledRunIsolationProfile) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "max_session_seconds": profile.max_session_seconds,
        "max_context_chars": profile.max_context_chars,
        "max_tool_calls": profile.max_tool_calls,
        "allowed_tool_ids": sorted(profile.allowed_tool_ids),
        "command_sandbox_profile_id": profile.command_sandbox_profile_id,
    }


__all__ = [
    "ScheduledRunIsolationError",
    "ScheduledRunIsolationGuard",
    "isolation_payload",
]
