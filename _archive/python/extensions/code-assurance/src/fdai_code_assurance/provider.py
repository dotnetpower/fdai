"""FDAI reasoning-tool provider for read-only pull-request assurance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.core.tools import ToolArtifact

from .analyzer import analyze_snapshot
from .models import PullRequestSnapshot, ReviewProfile

CODE_REVIEW_TOOL_ID = "code-assurance.review-pr"
SECURITY_REVIEW_TOOL_ID = "code-assurance.security-review"


class PullRequestSource(Protocol):
    async def fetch(self, *, repository: str, pull_number: int) -> PullRequestSnapshot: ...


@dataclass(frozen=True, slots=True)
class CodeAssuranceProvider:
    source: PullRequestSource

    async def call(
        self,
        *,
        artifact: ToolArtifact,
        arguments: Mapping[str, Any],
    ) -> object:
        profile = _profile(artifact.id)
        repository = arguments.get("repository")
        pull_number = arguments.get("pull_number")
        if not isinstance(repository, str) or not repository:
            raise ValueError("repository MUST be a non-empty string")
        if not isinstance(pull_number, int) or isinstance(pull_number, bool) or pull_number < 1:
            raise ValueError("pull_number MUST be a positive integer")
        snapshot = await self.source.fetch(
            repository=repository,
            pull_number=pull_number,
        )
        return analyze_snapshot(snapshot, profile=profile).to_dict()


def _profile(tool_id: str) -> ReviewProfile:
    if tool_id == CODE_REVIEW_TOOL_ID:
        return ReviewProfile.CODE
    if tool_id == SECURITY_REVIEW_TOOL_ID:
        return ReviewProfile.SECURITY
    raise ValueError(f"unsupported code-assurance tool id {tool_id!r}")


__all__ = [
    "CODE_REVIEW_TOOL_ID",
    "SECURITY_REVIEW_TOOL_ID",
    "CodeAssuranceProvider",
    "PullRequestSource",
]
