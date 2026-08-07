"""Transport-neutral post-turn review submission contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from fdai.core.operator_memory import ScopeKind
from fdai.shared.providers.user_context import ConversationTurnRecord

_CORRECTION_MARKERS = (
    re.compile(r"\b(?:no|instead|next time|do not|don't|should have)\b", re.IGNORECASE),
    re.compile(r"(?:아니|대신|다음부터|하지 마|해야 했)"),
)


@dataclass(frozen=True, slots=True)
class PostTurnReviewSubmission:
    """Bounded evidence submitted for off-path review of a completed turn."""

    validation_outcomes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    explicit_corrections: tuple[str, ...] = ()
    memory_scope_kind: ScopeKind | None = None
    memory_scope_ref: str | None = None


class PostTurnReviewSubmitter(Protocol):
    """Submit a completed exchange without extending response latency."""

    def submit_nowait(
        self,
        *,
        operator_turn: ConversationTurnRecord,
        assistant_turn: ConversationTurnRecord,
        submission: PostTurnReviewSubmission,
    ) -> bool: ...


def explicit_corrections(prompt: str) -> tuple[str, ...]:
    """Return the bounded prompt only when it carries a correction marker."""

    return (prompt,) if any(pattern.search(prompt) for pattern in _CORRECTION_MARKERS) else ()


__all__ = [
    "PostTurnReviewSubmission",
    "PostTurnReviewSubmitter",
    "explicit_corrections",
]
