"""Pantheon assurance terminal projection tests."""

from typing import Any, cast

from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_done_event_data,
)
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnProjectionConsumer,
)
from fdai_operator_service.postgres_family_store import StoredSemanticResult


def _assurance() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "answer": "Bounded Pantheon answer.",
        "assessment_id": "conversation-assessment:test",
        "trace_receipt_id": "a" * 64,
        "pantheon_trace": {"receipt_digest": "a" * 64},
        "pantheon_observations": {"read_only": True},
        "pantheon_semantic_reviews": [],
        "pantheon_diagnostic": {"score": 25},
        "execution_authority": False,
    }


def _semantic_fallback() -> dict[str, object]:
    return {
        "disposition": "held",
        "reason_code": "semantic_runtime_unavailable",
        "unavailable_reason": "semantic_planner_unavailable",
        "session_id": "session-one",
        "turn_id": "turn-one",
        "turn_sequence": 0,
        "evidence_refs": [],
        "checks_completed": 0,
        "checks_total": 0,
        "answer": "The request was held because verified evidence is unavailable.",
        "execution_authority": False,
    }


def test_pantheon_assurance_projection_becomes_one_bounded_terminal_answer() -> None:
    done = semantic_done_event_data(
        {
            "payload": {
                "pantheon_assurance": _assurance(),
            }
        }
    )

    assert done["status"] == "answered"
    assert done["answer"] == "Bounded Pantheon answer."
    assert done["source"] == "pantheon-conversation-assurance"
    assert done["execution_authority"] is False


class _Store:
    def __init__(self) -> None:
        self.projection: dict[str, object] | None = None

    async def project_semantic_turn_result(
        self,
        *,
        projection: dict[str, object],
    ) -> StoredSemanticResult:
        self.projection = projection
        return cast(StoredSemanticResult, object())


async def test_projection_consumer_accepts_valid_pantheon_assurance_extension() -> None:
    store = _Store()
    consumer = SemanticTurnProjectionConsumer(store=cast(Any, store))
    projection = {
        "schema_version": "1.4.0",
        "projection_id": "00000000-0000-0000-0000-000000000001",
        "request_id": "00000000-0000-0000-0000-000000000002",
        "correlation_id": "correlation-one",
        "idempotency_key": "idempotency-one",
        "status": "held",
        "recorded_at": "2026-08-30T12:00:00Z",
        "payload": {
            "request_kind": "pantheon_conversation_assurance",
            "request_digest": "sha256:" + ("b" * 64),
            "pantheon_assurance": _assurance(),
        },
        "evidence_digest": "sha256:" + ("c" * 64),
        "semantic_result": _semantic_fallback(),
    }

    await consumer.consume(projection)

    assert store.projection is not None
    assert store.projection["status"] == "held"
