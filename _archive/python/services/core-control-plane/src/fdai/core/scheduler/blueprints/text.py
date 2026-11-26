"""Bounded optional human-readable text drafting for blueprint cards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fdai.core.scheduler.blueprints.models import AutomationBlueprintCandidate


@dataclass(frozen=True, slots=True)
class AutomationBlueprintTextDraft:
    name: str
    prompt: str

    def __post_init__(self) -> None:
        _validate("name", self.name, 128)
        _validate("prompt", self.prompt, 2_000)


class AutomationBlueprintTextDrafter(Protocol):
    async def draft(
        self,
        candidate: AutomationBlueprintCandidate,
        *,
        max_chars: int,
    ) -> AutomationBlueprintTextDraft: ...


async def draft_blueprint_text(
    candidate: AutomationBlueprintCandidate,
    *,
    drafter: AutomationBlueprintTextDrafter | None,
    max_chars: int = 2_000,
) -> AutomationBlueprintTextDraft:
    if not 1 <= max_chars <= 2_000:
        raise ValueError("blueprint text budget MUST be in [1, 2000]")
    if drafter is None:
        return AutomationBlueprintTextDraft(
            name=candidate.normalized_task_intent[:128],
            prompt=candidate.normalized_task_intent[:max_chars],
        )
    draft = await drafter.draft(candidate, max_chars=max_chars)
    if len(draft.name) + len(draft.prompt) > max_chars:
        raise ValueError("blueprint text draft exceeds the configured budget")
    return draft


def _validate(label: str, value: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum or any(ord(character) < 32 for character in value):
        raise ValueError(f"blueprint text {label} MUST be bounded printable text")


__all__ = [
    "AutomationBlueprintTextDraft",
    "AutomationBlueprintTextDrafter",
    "draft_blueprint_text",
]
