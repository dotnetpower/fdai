"""Server-owned capability profiles for isolated task workers."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.read_investigation import ReadToolId


@dataclass(frozen=True, slots=True)
class TaskWorkerCapabilityProfile:
    profile_id: str
    allowed_tools: frozenset[str]

    def __post_init__(self) -> None:
        if self.profile_id != "background.read-only":
            raise ValueError("only the background.read-only profile is supported")
        expected = frozenset(tool.value for tool in ReadToolId)
        if self.allowed_tools != expected:
            raise ValueError("background.read-only MUST contain the seven investigation tools")


BACKGROUND_READ_ONLY_PROFILE = TaskWorkerCapabilityProfile(
    profile_id="background.read-only",
    allowed_tools=frozenset(tool.value for tool in ReadToolId),
)


def task_worker_profile(profile_id: str) -> TaskWorkerCapabilityProfile:
    if profile_id != BACKGROUND_READ_ONLY_PROFILE.profile_id:
        raise LookupError(f"unknown task worker profile {profile_id!r}")
    return BACKGROUND_READ_ONLY_PROFILE


__all__ = [
    "BACKGROUND_READ_ONLY_PROFILE",
    "TaskWorkerCapabilityProfile",
    "task_worker_profile",
]
