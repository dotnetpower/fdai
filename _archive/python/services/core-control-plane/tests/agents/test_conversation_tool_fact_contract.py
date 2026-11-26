"""Conversation tool fact-scope contracts for Pantheon agents."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.agents._framework.arbitration import RecentDecision
from fdai.agents._framework.factory import instantiate_pantheon
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents.loki import Loki
from fdai.agents.norns import Norns
from fdai.agents.odin import DecisionHistory, Odin
from fdai.core.learning import PostTurnReviewInput, review_input_to_mapping

_NOW = datetime(2026, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("agent_name", "tool_id"),
    tuple(
        (spec.name, tool.tool_id)
        for spec in PANTHEON_SPECS
        for tool in spec.conversation.tool_specs
    ),
)
async def test_declared_tool_facts_are_produced_for_unselected_and_selected_questions(
    agent_name: str,
    tool_id: str,
) -> None:
    """Every declared fact key is present or the whole tool explicitly abstains."""
    agent = instantiate_pantheon()[agent_name]
    tool = agent.spec.conversation.tool(tool_id)
    assert tool is not None

    for question in (
        f"What is the {tool_id} state?",
        f"What is the {tool_id} state for selected-resource selected.correlation selected_bucket?",
    ):
        envelope = await agent.on_conversation_turn(question, {"conversation_tool": tool_id})
        if envelope["abstain_reason"] is not None:
            assert envelope["abstain_reason"]
            continue

        facts = envelope["facts"]
        assert envelope["answer"], f"{agent_name}:{tool_id}:{question}"
        assert facts["agent"] == agent_name
        assert "evidence_refs" in facts
        missing = [key for key in tool.fact_keys if key not in facts]
        assert missing == [], f"{agent_name}:{tool_id}:{missing}"


async def test_loki_resilience_projection_uses_selected_tool_not_lexical_substrings() -> None:
    loki = Loki()
    loki._resilience_scores["resource-1"] = (0.72, "2028-01-02T00:00:00+00:00")  # noqa: SLF001

    selected = await loki.introspect(
        "status for resource-1",
        {"conversation_tool": "read_resilience_scores"},
    )
    assert selected.facts["resilience_score"] == 0.72

    lexical_only = await loki.introspect("resilience score for resource-1", {})
    assert lexical_only.facts["resilience_score"] is None


async def test_loki_chaos_safety_does_not_hide_in_flight_target_state() -> None:
    loki = Loki()
    loki._in_flight_targets.add("resource-1")  # noqa: SLF001

    result = await loki.introspect(
        "What is chaos safety?",
        {"conversation_tool": "read_chaos_safety"},
    )

    assert result.facts["in_flight_target_count"] == 1
    assert result.facts["in_flight_targets"] is None


class _PostTurnCoordinator:
    def __init__(self) -> None:
        self.inputs: list[PostTurnReviewInput] = []

    async def review(self, review_input: PostTurnReviewInput) -> object:
        self.inputs.append(review_input)
        return object()


def _post_turn_payload() -> dict[str, object]:
    review = PostTurnReviewInput(
        review_id="review-duplicate-1",
        principal_scope="principal-hash-1",
        operator_turn_id="turn-operator-1",
        assistant_turn_id="turn-assistant-1",
        completed_at=_NOW,
    )
    return {
        "kind": "post_turn_review",
        "producer_principal": "Bragi",
        "idempotency_key": f"post-turn-review:{review.review_id}",
        "review": review_input_to_mapping(review),
    }


async def test_norns_post_turn_reviews_are_idempotent() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    payload = _post_turn_payload()

    await norns.on_typed_message("object.post-turn-review", payload)
    await norns.on_typed_message("object.post-turn-review", dict(payload))

    assert [item.review_id for item in coordinator.inputs] == ["review-duplicate-1"]
    assert norns.behavior_snapshot()["post_turn_review_duplicate"] == 1


async def test_norns_records_unsupported_post_turn_kind_without_learning() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]

    await norns.on_typed_message(
        "object.post-turn-review",
        {
            "producer_principal": "Bragi",
            "kind": "unexpected_post_turn_evidence",
            "correlation_id": "unexpected-kind-1",
            "idempotency_key": "unexpected-kind-1",
        },
    )

    assert coordinator.inputs == []
    assert norns.behavior_snapshot()["post_turn_review:unsupported_kind"] == 1


def test_norns_outcome_evidence_counts_as_conversation_evidence() -> None:
    norns = Norns()
    norns._outcomes.set("ops.restart-service", {"total": 1, "rollback": 1})  # noqa: SLF001

    assert norns.conversation_evidence_available({}) is True


class _FakeHistory(DecisionHistory):
    def __init__(self) -> None:
        self._records = (
            RecentDecision(
                winner="resilience",
                losers=("cost",),
                resource_id="resource-1",
                at=0.0,
            ),
        )

    async def recent(self, resource_id: str, *, limit: int) -> tuple[RecentDecision, ...]:
        return self._records[:limit]


async def test_odin_reports_bound_arbitration_history_seam_available() -> None:
    odin = Odin(history=_FakeHistory())

    result = await odin.introspect(
        "arbitration history",
        {"semantic_primary_intent": "arbitration_history"},
    )

    assert result.facts["arbitration_history_available"] is True
    assert result.facts["evidence_refs"]
    assert "history seam is bound" in result.answer
