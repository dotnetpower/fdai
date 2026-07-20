from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.learning import (
    ConsensusPostTurnReviewer,
    NoImprovement,
    OperatorMemoryCandidate,
    PostTurnReviewInput,
)
from fdai.core.operator_memory import MemoryCategory, ScopeKind

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _input() -> PostTurnReviewInput:
    return PostTurnReviewInput(
        review_id="review-1",
        principal_scope="principal-hash-1",
        operator_turn_id="turn-operator-1",
        assistant_turn_id="turn-assistant-1",
        completed_at=_NOW,
        operator_body="Use the scoped query.",
        assistant_body="The scoped query succeeded.",
        explicit_corrections=("Use the scoped query next time.",),
        evidence_refs=("audit:1",),
        memory_scope_kind=ScopeKind.RESOURCE,
        memory_scope_ref="/subscriptions/example/resourceGroups/example/providers/example/type/one",
    )


def _candidate() -> OperatorMemoryCandidate:
    return OperatorMemoryCandidate(
        scope_kind=ScopeKind.RESOURCE,
        scope_ref="/subscriptions/example/resourceGroups/example/providers/example/type/one",
        category=MemoryCategory.RUNBOOK_HINT,
        body="Use the scoped query before escalation.",
        evidence_refs=("audit:1",),
        confidence=0.9,
    )


class _Model:
    def __init__(self, identity: str, family: str, result: object) -> None:
        self.model_identity = identity
        self.model_family = family
        self.result = result

    async def propose(self, review_input: PostTurnReviewInput) -> object:
        return self.result


def _reviewer(first: object, second: object) -> ConsensusPostTurnReviewer:
    return ConsensusPostTurnReviewer(
        (
            _Model("model-a", "family-a", first),  # type: ignore[arg-type]
            _Model("model-b", "family-b", second),  # type: ignore[arg-type]
        )
    )


async def test_exact_supported_agreement_returns_proposal() -> None:
    candidate = _candidate()

    assert await _reviewer(candidate, candidate).review(_input()) == candidate


async def test_content_disagreement_abstains() -> None:
    first = _candidate()
    second = replace(first, body="Use another query before escalation.")

    assert await _reviewer(first, second).review(_input()) == NoImprovement("model_disagreement")


async def test_unsupported_evidence_abstains() -> None:
    candidate = replace(_candidate(), evidence_refs=("audit:outside",))

    assert await _reviewer(candidate, candidate).review(_input()) == NoImprovement(
        "unsupported_evidence"
    )


async def test_memory_scope_mismatch_abstains() -> None:
    candidate = replace(_candidate(), scope_ref="resource:other")

    assert await _reviewer(candidate, candidate).review(_input()) == NoImprovement(
        "memory_scope_mismatch"
    )


def test_same_model_family_is_rejected_at_composition() -> None:
    with pytest.raises(ValueError, match="families MUST be distinct"):
        ConsensusPostTurnReviewer(
            (
                _Model("model-a", "family-a", _candidate()),  # type: ignore[arg-type]
                _Model("model-b", "family-a", _candidate()),  # type: ignore[arg-type]
            )
        )
