"""Provider contract for non-executing shell syntax checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.shared.providers.shell_task import ShellTaskSpec


@dataclass(frozen=True, slots=True)
class ShellCheckIssue:
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ShellCheckReport:
    artifact_hash: str
    checker_id: str
    issues: tuple[ShellCheckIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


@runtime_checkable
class ShellTaskChecker(Protocol):
    """Parse a shell artifact without executing its commands."""

    async def check(self, task: ShellTaskSpec) -> ShellCheckReport: ...


__all__ = ["ShellCheckIssue", "ShellCheckReport", "ShellTaskChecker"]
