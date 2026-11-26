from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.norns import Norns
from fdai.core.learning import (
    PostTurnReviewInput,
    RuleCandidateHint,
    review_input_to_mapping,
)
from fdai.shared.providers.user_context import UserPreferenceRecord

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


def _review_with_body(*, principal_id: str = "alice") -> PostTurnReviewInput:
    principal_scope = f"sha256:{hashlib.sha256(principal_id.encode()).hexdigest()}"
    return PostTurnReviewInput(
        review_id="review-body-1",
        principal_scope=principal_scope,
        operator_turn_id="turn-operator-body-1",
        assistant_turn_id="turn-assistant-body-1",
        completed_at=_NOW,
        operator_body="Inspect the bounded incident evidence.",
        assistant_body="The bounded inspection completed.",
    )


async def test_norns_consumes_only_bragi_owned_post_turn_envelope() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]

    await norns.on_typed_message(
        "object.post-turn-review",
        {
            "producer_principal": "Bragi",
            "kind": "post_turn_review",
            "review": review_input_to_mapping(_review_input()),
        },
    )

    assert coordinator.inputs == [_review_input()]


async def test_bragi_opted_in_post_turn_body_reaches_norns() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    coordinator = _PostTurnCoordinator()
    bragi = Bragi()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    bragi.bind_bus(bus)
    bus.subscribe("object.post-turn-review", "Norns", norns.on_typed_message)
    review = _review_with_body()
    preference = UserPreferenceRecord(
        principal_id="alice",
        share_with_learner=True,
        revision=7,
        updated_at=_NOW,
    )

    assert await bragi.publish_post_turn_review(review, preference=preference)

    assert coordinator.inputs == [review]
    payload = bus.messages_on("object.post-turn-review")[0].payload
    assert payload["body_consent"] == {
        "share_with_learner": True,
        "principal_scope": review.principal_scope,
        "consent_ref": f"user-preference:{review.principal_scope}:7",
    }


async def test_bragi_non_opted_in_post_turn_review_is_metadata_only_for_norns() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    coordinator = _PostTurnCoordinator()
    bragi = Bragi()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    bragi.bind_bus(bus)
    bus.subscribe("object.post-turn-review", "Norns", norns.on_typed_message)
    review = _review_with_body()
    preference = UserPreferenceRecord(
        principal_id="alice",
        share_with_learner=False,
        revision=8,
        updated_at=_NOW,
    )

    assert await bragi.publish_post_turn_review(review, preference=preference)

    expected = PostTurnReviewInput(
        review_id=review.review_id,
        principal_scope=review.principal_scope,
        operator_turn_id=review.operator_turn_id,
        assistant_turn_id=review.assistant_turn_id,
        completed_at=review.completed_at,
    )
    assert coordinator.inputs == [expected]
    payload = bus.messages_on("object.post-turn-review")[0].payload
    assert "body_consent" not in payload
    assert payload["review"]["operator_body"] is None
    assert payload["review"]["assistant_body"] is None


async def test_norns_rejects_post_turn_envelope_from_another_producer() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]

    await norns.on_typed_message(
        "object.post-turn-review",
        {
            "producer_principal": "Thor",
            "kind": "post_turn_review",
            "correlation_id": "review-1",
            "idempotency_key": "post-turn-review:review-1",
            "review": review_input_to_mapping(_review_input()),
        },
    )

    assert coordinator.inputs == []
    assert norns.behavior_snapshot()["post_turn_review:invalid_producer"] == 1


async def test_forged_body_consent_from_non_bragi_producer_is_rejected() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    review = _review_with_body()

    await norns.on_typed_message(
        "object.post-turn-review",
        {
            "producer_principal": "Mallory",
            "kind": "post_turn_review",
            "correlation_id": review.review_id,
            "idempotency_key": f"post-turn-review:{review.review_id}",
            "body_consent": {
                "share_with_learner": True,
                "principal_scope": review.principal_scope,
                "consent_ref": f"user-preference:{review.principal_scope}:1",
            },
            "review": review_input_to_mapping(review),
        },
    )

    assert coordinator.inputs == []
    assert norns.behavior_snapshot()["post_turn_review:invalid_producer"] == 1
