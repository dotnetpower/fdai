from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.agents.norns import Norns
from fdai.core.learning import (
    PostTurnReviewInput,
    RuleCandidateHint,
    review_input_to_mapping,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _hint() -> RuleCandidateHint:
    return RuleCandidateHint(
        proposal_kind="revision",
        target_ref="rule-1",
        pattern="Repeated correction indicates a narrower condition.",
        evidence_refs=("audit:1",),
        confidence=0.8,
    )


async def test_norns_converts_verified_hint_into_one_inert_candidate() -> None:
    norns = Norns()

    first = await norns.submit_rule_hint(_hint(), proposed_by="Norns", at=_NOW)
    second = await norns.submit_rule_hint(_hint(), proposed_by="Norns", at=_NOW)

    assert first == second
    assert len(norns.pending_candidates) == 1
    candidate = norns.pending_candidates[0]
    assert candidate["source_signal"] == "post_turn_review"
    assert candidate["proposal_kind"] == "revision"
    assert candidate["target_rule_id"] == "rule-1"
    assert candidate["proposed_by"] == "Norns"


async def test_norns_rejects_another_proposer_identity() -> None:
    norns = Norns()

    with pytest.raises(ValueError, match="MUST be proposed by Norns"):
        await norns.submit_rule_hint(_hint(), proposed_by="Bragi", at=_NOW)

    assert norns.pending_candidates == []


async def test_norns_requires_aware_hint_timestamp() -> None:
    norns = Norns()

    with pytest.raises(ValueError, match="timezone-aware"):
        await norns.submit_rule_hint(
            _hint(),
            proposed_by="Norns",
            at=datetime(2026, 7, 20),
        )


class _PostTurnCoordinator:
    def __init__(self) -> None:
        self.inputs: list[PostTurnReviewInput] = []

    async def review(self, review_input: PostTurnReviewInput) -> object:
        self.inputs.append(review_input)
        return object()


def _review_input() -> PostTurnReviewInput:
    return PostTurnReviewInput(
        review_id="review-1",
        principal_scope="principal-hash-1",
        operator_turn_id="turn-operator-1",
        assistant_turn_id="turn-assistant-1",
        completed_at=_NOW,
    )


async def test_norns_consumes_only_bragi_owned_post_turn_envelope() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]

    await norns.on_typed_message(
        "object.turn",
        {
            "producer_principal": "Bragi",
            "kind": "post_turn_review",
            "review": review_input_to_mapping(_review_input()),
        },
    )

    assert coordinator.inputs == [_review_input()]


async def test_norns_rejects_post_turn_envelope_from_another_producer() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="published by Bragi"):
        await norns.on_typed_message(
            "object.turn",
            {
                "producer_principal": "Thor",
                "kind": "post_turn_review",
                "review": review_input_to_mapping(_review_input()),
            },
        )

    assert coordinator.inputs == []
