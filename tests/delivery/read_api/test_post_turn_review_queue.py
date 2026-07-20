from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fdai.core.learning import (
    InMemoryPostTurnReviewLedger,
    NoImprovement,
    PostTurnEligibilityPolicy,
    PostTurnReviewCoordinator,
)
from fdai.delivery.read_api.routes.post_turn_review import (
    PostTurnReviewQueue,
    PostTurnReviewQueueConfig,
    PostTurnReviewSubmission,
    explicit_corrections,
)
from fdai.shared.providers.testing import InMemoryUserPreferenceStore
from fdai.shared.providers.user_context import (
    ConversationTurnRecord,
    ConversationTurnRole,
    UserPreferenceRecord,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _turn(role: ConversationTurnRole, content: str) -> ConversationTurnRecord:
    suffix = role.value
    return ConversationTurnRecord(
        turn_id=f"turn-{suffix}-1",
        conversation_id="conversation-1",
        principal_id="principal-1",
        turn_index=0 if role is ConversationTurnRole.OPERATOR else 1,
        role=role,
        content=content,
        recorded_at=_NOW,
        idempotency_key=f"request-1:{suffix}",
    )


class _Reviewer:
    def __init__(self) -> None:
        self.inputs: list[object] = []

    async def review(self, review_input: object) -> NoImprovement:
        self.inputs.append(review_input)
        return NoImprovement("no_reusable_improvement")


class _Router:
    async def route(self, proposal: object, *, proposed_by: str, at: datetime) -> str:
        raise AssertionError("abstaining reviewer must not route")


class _CoordinatorIntake:
    def __init__(self, coordinator: PostTurnReviewCoordinator) -> None:
        self._coordinator = coordinator

    async def submit(self, review_input: object) -> None:
        await self._coordinator.review(review_input)  # type: ignore[arg-type]


def _queue(
    preferences: InMemoryUserPreferenceStore,
    reviewer: _Reviewer,
    *,
    max_pending: int = 64,
) -> PostTurnReviewQueue:
    return PostTurnReviewQueue(
        preferences=preferences,
        intake=_CoordinatorIntake(
            PostTurnReviewCoordinator(
                eligibility=PostTurnEligibilityPolicy(),
                reviewer=reviewer,  # type: ignore[arg-type]
                router=_Router(),  # type: ignore[arg-type]
                ledger=InMemoryPostTurnReviewLedger(),
                now=lambda: _NOW,
            )
        ),
        config=PostTurnReviewQueueConfig(
            max_pending=max_pending,
            retry_attempts=1,
            retry_backoff_seconds=0,
        ),
    )


async def test_submit_returns_before_review_and_honors_learner_consent() -> None:
    preferences = InMemoryUserPreferenceStore()
    await preferences.put(
        UserPreferenceRecord(
            principal_id="principal-1",
            share_with_learner=True,
        )
    )
    reviewer = _Reviewer()
    queue = _queue(preferences, reviewer)

    accepted = queue.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "No, use the scoped query."),
        assistant_turn=_turn(ConversationTurnRole.ASSISTANT, "The scoped query succeeded."),
        submission=PostTurnReviewSubmission(
            validation_outcomes=("verified",),
            evidence_refs=("audit:1",),
            explicit_corrections=("No, use the scoped query.",),
        ),
    )

    assert accepted is True
    assert reviewer.inputs == []
    await queue.close()
    assert len(reviewer.inputs) == 1
    review_input = reviewer.inputs[0]
    assert review_input.operator_body == "No, use the scoped query."  # type: ignore[attr-defined]


async def test_opted_out_turn_reaches_only_metadata_eligibility() -> None:
    preferences = InMemoryUserPreferenceStore()
    reviewer = _Reviewer()
    queue = _queue(preferences, reviewer)

    queue.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "No, use the scoped query."),
        assistant_turn=_turn(ConversationTurnRole.ASSISTANT, "The scoped query succeeded."),
        submission=PostTurnReviewSubmission(
            validation_outcomes=("verified",),
            evidence_refs=("audit:1",),
            explicit_corrections=("No, use the scoped query.",),
        ),
    )
    await queue.close()

    assert reviewer.inputs == []


async def test_pending_bound_rejects_without_blocking() -> None:
    preferences = InMemoryUserPreferenceStore()
    reviewer = _Reviewer()
    queue = _queue(preferences, reviewer, max_pending=1)
    gate = asyncio.Event()
    original_get = preferences.get

    async def blocked_get(*, principal_id: str):  # noqa: ANN202
        await gate.wait()
        return await original_get(principal_id=principal_id)

    preferences.get = blocked_get  # type: ignore[method-assign]
    submission = PostTurnReviewSubmission(
        validation_outcomes=("verified",),
        evidence_refs=("audit:1",),
    )

    first = queue.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "Inspect."),
        assistant_turn=_turn(ConversationTurnRole.ASSISTANT, "Done."),
        submission=submission,
    )
    second = queue.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "Inspect."),
        assistant_turn=_turn(ConversationTurnRole.ASSISTANT, "Done."),
        submission=submission,
    )
    gate.set()
    await queue.close()

    assert first is True
    assert second is False


def test_explicit_correction_detection_is_deterministic() -> None:
    assert explicit_corrections("No, use the scoped query instead.")
    assert explicit_corrections("다음부터 범위가 좁은 쿼리를 사용해.")
    assert explicit_corrections("Inspect the current incident.") == ()
