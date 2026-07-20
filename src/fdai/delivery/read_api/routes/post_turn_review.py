"""Bounded off-path submission of completed conversation turns."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from fdai.core.conversation.learner_access import project_turn_for_learner
from fdai.core.learning import PostTurnReviewInput
from fdai.core.operator_memory import ScopeKind
from fdai.shared.providers.user_context import (
    ConversationTurnRecord,
    UserPreferenceStore,
)

_CORRECTION_MARKERS = (
    re.compile(r"\b(?:no|instead|next time|do not|don't|should have)\b", re.IGNORECASE),
    re.compile(r"(?:아니|대신|다음부터|하지 마|해야 했)"),
)


@dataclass(frozen=True, slots=True)
class PostTurnReviewSubmission:
    validation_outcomes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    explicit_corrections: tuple[str, ...] = ()
    memory_scope_kind: ScopeKind | None = None
    memory_scope_ref: str | None = None


class PostTurnReviewSubmitter(Protocol):
    def submit_nowait(
        self,
        *,
        operator_turn: ConversationTurnRecord,
        assistant_turn: ConversationTurnRecord,
        submission: PostTurnReviewSubmission,
    ) -> bool: ...


class PostTurnReviewIntake(Protocol):
    async def submit(self, review_input: PostTurnReviewInput) -> None: ...


@dataclass(frozen=True, slots=True)
class PostTurnReviewQueueConfig:
    max_pending: int = 64
    retry_attempts: int = 3
    retry_backoff_seconds: float = 0.1

    def __post_init__(self) -> None:
        if not 1 <= self.max_pending <= 1_024:
            raise ValueError("post-turn max_pending MUST be in [1, 1024]")
        if not 1 <= self.retry_attempts <= 10:
            raise ValueError("post-turn retry_attempts MUST be in [1, 10]")
        if self.retry_backoff_seconds < 0:
            raise ValueError("post-turn retry_backoff_seconds MUST be >= 0")


class PostTurnReviewQueue:
    """Schedule review outside response latency with bounded retries."""

    def __init__(
        self,
        *,
        preferences: UserPreferenceStore,
        intake: PostTurnReviewIntake,
        config: PostTurnReviewQueueConfig | None = None,
        sleep: Callable[[float], Awaitable[object]] | None = None,
    ) -> None:
        self._preferences = preferences
        self._intake = intake
        self._config = config or PostTurnReviewQueueConfig()
        self._sleep = sleep or asyncio.sleep
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def pending(self) -> int:
        return len(self._tasks)

    def submit_nowait(
        self,
        *,
        operator_turn: ConversationTurnRecord,
        assistant_turn: ConversationTurnRecord,
        submission: PostTurnReviewSubmission,
    ) -> bool:
        if operator_turn.principal_id != assistant_turn.principal_id:
            raise ValueError("post-turn exchange principals MUST match")
        if operator_turn.conversation_id != assistant_turn.conversation_id:
            raise ValueError("post-turn exchange conversations MUST match")
        if len(self._tasks) >= self._config.max_pending:
            return False
        task = asyncio.create_task(
            self._run(
                operator_turn=operator_turn,
                assistant_turn=assistant_turn,
                submission=submission,
            ),
            name=f"post-turn-review:{assistant_turn.turn_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def _run(
        self,
        *,
        operator_turn: ConversationTurnRecord,
        assistant_turn: ConversationTurnRecord,
        submission: PostTurnReviewSubmission,
    ) -> None:
        for attempt in range(self._config.retry_attempts):
            try:
                preference = await self._preferences.get(principal_id=operator_turn.principal_id)
                operator_view = project_turn_for_learner(
                    operator_turn,
                    preference=preference,
                )
                assistant_view = project_turn_for_learner(
                    assistant_turn,
                    preference=preference,
                )
                await self._intake.submit(
                    PostTurnReviewInput(
                        review_id=_review_id(assistant_turn.turn_id),
                        principal_scope=_principal_scope(operator_turn.principal_id),
                        operator_turn_id=operator_turn.turn_id,
                        assistant_turn_id=assistant_turn.turn_id,
                        completed_at=assistant_turn.recorded_at,
                        operator_body=operator_view.body,
                        assistant_body=assistant_view.body,
                        validation_outcomes=submission.validation_outcomes,
                        explicit_corrections=submission.explicit_corrections,
                        evidence_refs=submission.evidence_refs,
                        memory_scope_kind=submission.memory_scope_kind,
                        memory_scope_ref=submission.memory_scope_ref,
                    )
                )
                return
            except Exception:  # noqa: BLE001 - bounded retry; original response already completed
                if attempt + 1 >= self._config.retry_attempts:
                    return
                delay = self._config.retry_backoff_seconds * (2**attempt)
                await self._sleep(delay)


def explicit_corrections(prompt: str) -> tuple[str, ...]:
    """Return the bounded prompt only when it carries a correction marker."""
    return (prompt,) if any(pattern.search(prompt) for pattern in _CORRECTION_MARKERS) else ()


def _review_id(assistant_turn_id: str) -> str:
    digest = hashlib.sha256(assistant_turn_id.encode()).hexdigest()[:32]
    return f"review-{digest}"


def _principal_scope(principal_id: str) -> str:
    digest = hashlib.sha256(principal_id.encode()).hexdigest()[:32]
    return f"principal-{digest}"


__all__ = [
    "PostTurnReviewQueue",
    "PostTurnReviewQueueConfig",
    "PostTurnReviewIntake",
    "PostTurnReviewSubmission",
    "PostTurnReviewSubmitter",
    "explicit_corrections",
]
