"""Bragi-owned session, preference, and post-turn publication contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.norns import Norns
from fdai.core.learning import PostTurnReviewInput
from fdai.shared.providers.user_context import UserPreferenceRecord


class _PostTurnCoordinator:
    def __init__(self) -> None:
        self.inputs: list[PostTurnReviewInput] = []

    async def review(self, review_input: PostTurnReviewInput) -> object:
        self.inputs.append(review_input)
        return object()


def _bragi(bus: InMemoryBus) -> Bragi:
    bragi = Bragi()
    bragi.bind_bus(bus)
    return bragi


async def test_bragi_publishes_one_conversation_before_session_turns() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = _bragi(bus)

    await bragi.ask(session_id="session-1", user_id="operator-1", question="unknown one")
    await bragi.ask(session_id="session-1", user_id="operator-1", question="unknown two")

    (conversation,) = bus.messages_on("object.conversation")
    assert conversation.principal == "Bragi"
    assert conversation.payload["status"] == "active"
    assert conversation.payload["principal_scope"].startswith("sha256:")
    assert "operator-1" not in str(conversation.payload)
    assert len(bus.messages_on("object.turn")) == 2
    assert bus.published.index(conversation) < bus.published.index(
        bus.messages_on("object.turn")[0]
    )


async def test_bragi_publishes_validated_user_preference_without_raw_principal() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = _bragi(bus)
    preference = UserPreferenceRecord(
        principal_id="operator-1",
        locale="ko",
        verbosity="detailed",
        timezone="Asia/Seoul",
        share_with_learner=True,
        revision=3,
        updated_at=datetime(2028, 1, 2, tzinfo=UTC),
    )

    assert await bragi.publish_user_preference(preference) is True

    (message,) = bus.messages_on("object.user-preference")
    assert message.payload["locale"] == "ko"
    assert message.payload["revision"] == 3
    assert message.payload["share_with_learner"] is True
    assert message.payload["preference_digest"].startswith("sha256:")
    assert message.payload["idempotency_key"].endswith(":3")
    assert "operator-1" not in str(message.payload)


async def test_bragi_post_turn_review_reaches_norns_off_path() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = _bragi(bus)
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    bus.subscribe("object.post-turn-review", "Norns", norns.on_typed_message)
    review = PostTurnReviewInput(
        review_id="review-1",
        principal_scope="principal-hash-1",
        operator_turn_id="operator-turn-1",
        assistant_turn_id="assistant-turn-1",
        completed_at=datetime(2028, 1, 2, tzinfo=UTC),
        evidence_refs=("audit:1",),
    )

    assert await bragi.publish_post_turn_review(review) is True

    assert coordinator.inputs == [review]
    (message,) = bus.messages_on("object.post-turn-review")
    assert message.principal == "Bragi"
    assert message.payload["kind"] == "post_turn_review"


async def test_bragi_optional_publications_report_unavailable_without_bus() -> None:
    bragi = Bragi()
    preference = UserPreferenceRecord(
        principal_id="operator-1",
        revision=1,
        updated_at=datetime(2028, 1, 2, tzinfo=UTC),
    )
    review = PostTurnReviewInput(
        review_id="review-1",
        principal_scope="principal-hash-1",
        operator_turn_id="operator-turn-1",
        assistant_turn_id="assistant-turn-1",
        completed_at=datetime(2028, 1, 2, tzinfo=UTC),
    )

    assert await bragi.publish_user_preference(preference) is False
    assert await bragi.publish_post_turn_review(review) is False
