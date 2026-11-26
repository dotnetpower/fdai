"""Round 5 Bragi/Saga/Muninn conversation boundary regressions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.adapters import InMemoryGithubIssueAdapter
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.muninn import Muninn
from fdai.agents.saga import Saga, compute_fingerprint
from fdai.core.learning import PostTurnReviewInput
from fdai.shared.providers.user_context import UserPreferenceRecord

from tests.agents.semantic_judgment_support import restart_action_type, semantic_test_boundary


def _bragi(**kwargs: Any) -> Bragi:
    return Bragi(
        semantic_judgment=semantic_test_boundary(),
        action_type_names=(restart_action_type().name,),
        **kwargs,
    )


async def _accepted_sink(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


async def _dedup_sink(_payload: dict[str, Any]) -> None:
    return None


def test_session_expiry_rotates_context_and_publishes_digest_only_ids() -> None:
    current = datetime(2028, 1, 1, tzinfo=UTC)

    def clock() -> datetime:
        return current

    bus = InMemoryBus(registry=load_pantheon())
    bragi = _bragi(clock=clock)
    bragi.bind_bus(bus)

    first = asyncio.run(
        bragi.ask(session_id="raw-session-secret", user_id="alice", question="Thor status")
    )
    current += timedelta(minutes=31)
    second = asyncio.run(
        bragi.ask(session_id="raw-session-secret", user_id="alice", question="Thor status again")
    )

    conversations = [message.payload for message in bus.messages_on("object.conversation")]
    turns = [message.payload for message in bus.messages_on("object.turn")]
    assert [payload["status"] for payload in conversations] == ["active", "ended", "active"]
    assert first.turn_index == 0
    assert second.turn_index == 0
    assert "raw-session-secret" not in str(conversations)
    assert "raw-session-secret" not in str(turns)


def test_prior_turns_ref_is_digest_only_and_forwarded_to_primary() -> None:
    captured_contexts: list[dict[str, Any]] = []
    bragi = _bragi()

    async def responder(_question: str, context: dict[str, Any]) -> dict[str, Any]:
        captured_contexts.append(dict(context))
        return {
            "primary_agent": "Thor",
            "answer": "ok",
            "facts": {"evidence_refs": ["agent-state:Thor:sha256:" + ("a" * 64)]},
        }

    bragi.register_responder("Thor", responder)
    asyncio.run(bragi.ask(session_id="s", user_id="alice", question="Thor sentinel-secret"))
    asyncio.run(bragi.ask(session_id="s", user_id="alice", question="Thor follow-up"))

    assert "prior_turns_ref" not in captured_contexts[0]
    ref = captured_contexts[1]["prior_turns_ref"]
    assert ref.startswith("bragi-prior-turns:sha256:")
    assert "sentinel-secret" not in ref


def test_action_reentry_fails_closed_and_uses_principal_scoped_digests() -> None:
    bragi = _bragi()
    accepted: list[dict[str, Any]] = []

    async def sink(payload: dict[str, Any]) -> dict[str, Any]:
        accepted.append(payload)
        return payload

    bragi.register_proposal_sink(sink)
    missing_role = asyncio.run(
        bragi.ask(
            session_id="s",
            user_id="alice",
            question="restart svc-1 sentinel-secret",
            allow_action_proposal=True,
        )
    )
    assert missing_role.answer["submitted"] is False
    assert missing_role.answer["abstain_reason"] == "rbac_role_floor"

    submitted = asyncio.run(
        bragi.ask(
            session_id="s2",
            user_id="alice",
            question="restart svc-1 sentinel-secret",
            initiator_role="Contributor",
            allow_action_proposal=True,
        )
    )
    assert submitted.answer["submitted"] is True
    payload = accepted[-1]
    assert payload["initiator_principal"] == "alice"
    assert "sentinel-secret" not in str(payload["params"])
    assert payload["params"]["question_ref"].startswith("bragi-question:sha256:")
    first_key = payload["idempotency_key"]

    bragi_bob = _bragi()
    bragi_bob.register_proposal_sink(_accepted_sink)
    bob = asyncio.run(
        bragi_bob.ask(
            session_id="s2",
            user_id="bob",
            question="restart svc-1 sentinel-secret",
            initiator_role="Contributor",
            allow_action_proposal=True,
        )
    )
    assert bob.answer["correlation_id"] != first_key


def test_action_reentry_holds_unbound_target_and_reports_dedup() -> None:
    bragi = _bragi()
    bragi.register_proposal_sink(_accepted_sink)
    held = asyncio.run(
        bragi.ask(
            session_id="s",
            user_id="alice",
            question="restart now",
            initiator_role="Contributor",
            allow_action_proposal=True,
        )
    )
    assert held.answer["submitted"] is False
    assert held.answer["abstain_reason"] == "resource_target_required"

    dedup = _bragi()
    dedup.register_proposal_sink(_dedup_sink)
    turn = asyncio.run(
        dedup.ask(
            session_id="s",
            user_id="alice",
            question="restart svc-1",
            initiator_role="Contributor",
            allow_action_proposal=True,
        )
    )
    assert turn.answer["submitted"] is False
    assert turn.answer["deduplicated"] is True


def test_bragi_handoff_payload_and_saga_issue_metadata() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = _bragi()
    bragi.bind_bus(bus)
    turn = asyncio.run(
        bragi.ask(
            session_id="s",
            user_id="alice",
            question="zzzz qqqq",
            materialize_handoff=True,
        )
    )
    payload = bus.messages_on("object.handoff-escalation")[0].payload
    expected = compute_fingerprint(
        intent_category=payload["intent_category"],
        resource_type=payload["resource_type"],
        normalized_selector=payload["normalized_selector"],
        primary_agent=payload["primary_agent"],
        failure_reason_code=payload["failure_reason_code"],
    )
    assert turn.answer["handoff_status"] == "requested"
    assert payload["problem_fingerprint"] == expected
    assert payload["emitting_agent"] != "Bragi"

    github = InMemoryGithubIssueAdapter()
    saga = Saga(github=github)
    saga.bind_bus(bus)
    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))
    asyncio.run(
        saga.on_typed_message(
            "object.handoff-escalation",
            {
                **payload,
                "id": "handoff-repeat",
                "escalation_id": "handoff-repeat",
                "correlation_id": "handoff-repeat",
                "idempotency_key": "handoff:again",
            },
        )
    )
    issue = github.issues[expected]
    assert issue.labels == [f"fdai:fp:{expected}"]
    assert "First seen:" in issue.body
    assert "Last seen:" in issue.body
    assert "Occurrence count: 2" in issue.body


def test_muninn_requires_canonical_principal_scope_for_conversation_reads() -> None:
    muninn = Muninn()
    scope = "sha256:" + __import__("hashlib").sha256(b"alice").hexdigest()
    muninn.put_context("conversation_turns", "t1", {"principal_scope": scope, "answer_ref": "a"})

    assert muninn.get_context("conversation_turns", "t1") is None
    assert muninn.get_context("conversation_turns", "t1", requester_user_id="bob") is None
    assert muninn.get_context("conversation_turns", "t1", requester_user_id="alice") == {
        "principal_scope": scope,
        "answer_ref": "a",
    }


def test_a2a_refuses_nested_round_and_forwards_locale_with_monotonic_turns() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = _bragi()
    bragi.bind_bus(bus)
    contexts: list[dict[str, Any]] = []

    async def responder(_question: str, context: dict[str, Any]) -> dict[str, Any]:
        contexts.append(dict(context))
        return {
            "primary_agent": "Saga",
            "answer": "ok",
            "facts": {"evidence_refs": ["agent-state:Saga:sha256:" + ("a" * 64)]},
        }

    bragi.register_responder("Saga", responder)
    refused = asyncio.run(
        bragi.introspect_agent("Saga", "status", requester="Odin", context={"nested_round": True})
    )
    asyncio.run(
        bragi.introspect_agent("Saga", "status", requester="Odin", context={"locale": "ko"})
    )
    asyncio.run(bragi.introspect_agent("Saga", "again", requester="Odin", context={"locale": "ko"}))
    assert refused["abstain_reason"] == "nested_round_refused"
    assert contexts[0]["locale"] == "ko"
    assert [message.payload["turn_index"] for message in bus.messages_on("object.turn")] == [0, 1]


def test_post_turn_review_body_requires_share_with_learner() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = _bragi()
    bragi.bind_bus(bus)
    review = PostTurnReviewInput(
        review_id="review-1",
        principal_scope="sha256:" + __import__("hashlib").sha256(b"alice").hexdigest(),
        operator_turn_id="operator-turn-1",
        assistant_turn_id="assistant-turn-1",
        completed_at=datetime(2028, 1, 1, tzinfo=UTC),
        operator_body="raw operator",
        assistant_body="raw assistant",
    )

    asyncio.run(bragi.publish_post_turn_review(review))
    metadata_only = bus.messages_on("object.post-turn-review")[0].payload["review"]
    assert metadata_only["operator_body"] is None
    assert metadata_only["assistant_body"] is None

    preference = UserPreferenceRecord(
        principal_id="alice",
        share_with_learner=True,
        revision=1,
        updated_at=datetime(2028, 1, 1, tzinfo=UTC),
    )
    asyncio.run(bragi.publish_post_turn_review(review, preference=preference))
    shared = bus.messages_on("object.post-turn-review")[1].payload["review"]
    assert shared["operator_body"] == "raw operator"
    assert shared["assistant_body"] == "raw assistant"
