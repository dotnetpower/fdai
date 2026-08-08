from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.learning import (
    InMemoryPostTurnReviewLedger,
    NoImprovement,
    OperatorMemoryCandidate,
    PostTurnEligibilityPolicy,
    PostTurnReviewCoordinator,
    PostTurnReviewInput,
    PostTurnReviewMetrics,
    PostTurnReviewState,
)
from fdai.core.operator_memory.types import MemoryCategory, ScopeKind

_NOW = datetime(2026, 7, 20, 1, tzinfo=UTC)


def _input(review_id: str = "review-1") -> PostTurnReviewInput:
    return PostTurnReviewInput(
        review_id=review_id,
        principal_scope="principal-hash-1",
        operator_turn_id="turn-operator-1",
        assistant_turn_id="turn-assistant-1",
        completed_at=_NOW,
        operator_body="Inspect the incident.",
        assistant_body="Inspection completed.",
        explicit_corrections=("Use the resource-scoped query next time.",),
        evidence_refs=("audit:1",),
    )


def _candidate() -> OperatorMemoryCandidate:
    return OperatorMemoryCandidate(
        scope_kind=ScopeKind.RESOURCE,
        scope_ref="resource-hash-1",
        category=MemoryCategory.RUNBOOK_HINT,
        body="Use the resource-scoped query before escalation.",
        evidence_refs=("audit:1",),
        confidence=0.9,
    )


class _Reviewer:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def review(self, review_input: PostTurnReviewInput) -> object:  # type: ignore[override]
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Router:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def route(self, proposal: object, *, proposed_by: str, at: datetime) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert proposal == _candidate()
        assert proposed_by == "Norns"
        assert at == _NOW
        return "operator-memory-proposal:1"


def _coordinator(
    reviewer: _Reviewer,
    router: _Router,
    ledger: InMemoryPostTurnReviewLedger | None = None,
) -> PostTurnReviewCoordinator:
    return PostTurnReviewCoordinator(
        eligibility=PostTurnEligibilityPolicy(),
        reviewer=reviewer,  # type: ignore[arg-type]
        router=router,  # type: ignore[arg-type]
        ledger=ledger or InMemoryPostTurnReviewLedger(),
        metrics=PostTurnReviewMetrics(),
        now=lambda: _NOW,
    )


async def test_routes_eligible_proposal_to_owning_path() -> None:
    reviewer = _Reviewer(_candidate())
    router = _Router()
    coordinator = _coordinator(reviewer, router)

    record = await coordinator.review(_input())

    assert record.state is PostTurnReviewState.ROUTED
    assert record.proposal_ref == "operator-memory-proposal:1"
    assert reviewer.calls == 1
    assert router.calls == 1
    assert coordinator.metrics.snapshot().routed == 1


async def test_same_review_delivery_is_idempotent_before_reviewer() -> None:
    reviewer = _Reviewer(_candidate())
    router = _Router()
    coordinator = _coordinator(reviewer, router)

    first = await coordinator.review(_input())
    second = await coordinator.review(_input())

    assert second == first
    assert reviewer.calls == 1
    assert router.calls == 1
    assert coordinator.metrics.snapshot().duplicates == 1


async def test_content_duplicate_is_not_routed_twice() -> None:
    ledger = InMemoryPostTurnReviewLedger()
    reviewer = _Reviewer(_candidate())
    router = _Router()
    coordinator = _coordinator(reviewer, router, ledger)

    first = await coordinator.review(_input("review-1"))
    second = await coordinator.review(_input("review-2"))

    assert first.state is PostTurnReviewState.ROUTED
    assert second.state is PostTurnReviewState.DUPLICATE
    assert reviewer.calls == 2
    assert router.calls == 1


async def test_ineligible_turn_never_calls_reviewer_or_router() -> None:
    reviewer = _Reviewer(_candidate())
    router = _Router()
    coordinator = _coordinator(reviewer, router)
    review_input = PostTurnReviewInput(
        review_id="review-1",
        principal_scope="principal-hash-1",
        operator_turn_id="turn-operator-1",
        assistant_turn_id="turn-assistant-1",
        completed_at=_NOW,
    )

    record = await coordinator.review(review_input)

    assert record.state is PostTurnReviewState.INELIGIBLE
    assert reviewer.calls == 0
    assert router.calls == 0


async def test_no_improvement_is_a_bounded_abstention() -> None:
    coordinator = _coordinator(_Reviewer(NoImprovement("insufficient_evidence")), _Router())

    record = await coordinator.review(_input())

    assert record.state is PostTurnReviewState.ABSTAINED
    assert record.reasons == ("insufficient_evidence",)


async def test_reviewer_failure_is_recorded_and_not_raised() -> None:
    coordinator = _coordinator(_Reviewer(RuntimeError("provider unavailable")), _Router())

    record = await coordinator.review(_input())

    assert record.state is PostTurnReviewState.FAILED
    assert record.reasons == ("reviewer_error:RuntimeError",)


async def test_router_failure_is_recorded_and_not_raised() -> None:
    coordinator = _coordinator(_Reviewer(_candidate()), _Router(error=RuntimeError("down")))

    record = await coordinator.review(_input())

    assert record.state is PostTurnReviewState.FAILED
    assert record.reasons == ("router_error:RuntimeError",)
