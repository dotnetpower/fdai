"""Pantheon assurance terminal projection tests."""

from typing import Any, cast

import pytest
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
        "answer_generation": {
            "mode": "t2_model",
            "model_identity": "publisher-c:model-c",
            "model_family": "family-c",
        },
        "pantheon_evaluator_models": [
            {
                "model_identity": "publisher-a:reviewer-a",
                "model_family": "family-a",
                "output_available": True,
            },
            {
                "model_identity": "publisher-b:reviewer-b",
                "model_family": "family-b",
                "output_available": True,
            },
        ],
        "assessment_id": "conversation-assessment:test",
        "assessment_state": "completed",
        "assessment_reasons": ["mixed_family_consensus"],
        "trace_receipt_id": "a" * 64,
        "turn_timing": {
            "schema_version": 2,
            "started_at": "2026-08-30T12:00:00.000+00:00",
            "completed_at": "2026-08-30T12:00:00.025+00:00",
            "duration_ms": 25,
            "phases": [
                {
                    "phase": "pantheon_assurance",
                    "status": "completed",
                    "started_at": "2026-08-30T12:00:00.000+00:00",
                    "completed_at": "2026-08-30T12:00:00.025+00:00",
                    "duration_ms": 25,
                }
            ],
        },
        "pantheon_trace": {"receipt_digest": "a" * 64, "latency_ms": 20},
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
    assert done["answer_generation"] == {
        "mode": "t2_model",
        "model_identity": "publisher-c:model-c",
        "model_family": "family-c",
    }
    assert done["pantheon_evaluator_models"] == [
        {
            "model_identity": "publisher-a:reviewer-a",
            "model_family": "family-a",
            "output_available": True,
        },
        {
            "model_identity": "publisher-b:reviewer-b",
            "model_family": "family-b",
            "output_available": True,
        },
    ]
    assert done["assessment_state"] == "completed"
    assert done["assessment_reasons"] == ["mixed_family_consensus"]
    assert done["source"] == "pantheon-conversation-assurance"
    assert done["latency_ms"] == 20
    assert done["turn_timing"]["duration_ms"] == 25
    assert done["turn_timing"]["phases"][0]["phase"] == "pantheon_assurance"
    assert done["execution_authority"] is False


@pytest.mark.parametrize("assessment_state", ("deferred", "held", "unavailable"))
def test_incomplete_pantheon_assurance_is_not_presented_as_answered(
    assessment_state: str,
) -> None:
    assurance = _assurance()
    assurance["assessment_state"] = assessment_state
    assurance["assessment_reasons"] = ["evaluator_error:provider_http_429"]

    done = semantic_done_event_data({"payload": {"pantheon_assurance": assurance}})

    assert done["status"] == "held"
    assert done["answer"] == "Bounded Pantheon answer."
    assert done["assessment_state"] == assessment_state
    assert done["assessment_reasons"] == ["evaluator_error:provider_http_429"]


def test_legacy_pantheon_assurance_without_timing_remains_readable() -> None:
    assurance = _assurance()
    assurance.pop("turn_timing")
    trace = cast(dict[str, object], assurance["pantheon_trace"])
    trace.pop("latency_ms")

    done = semantic_done_event_data({"payload": {"pantheon_assurance": assurance}})

    assert done["answer"] == "Bounded Pantheon answer."
    assert "latency_ms" not in done
    assert "turn_timing" not in done


def test_legacy_pantheon_assurance_without_model_attribution_is_explicit() -> None:
    assurance = _assurance()
    assurance.pop("answer_generation")
    assurance.pop("pantheon_evaluator_models")

    done = semantic_done_event_data({"payload": {"pantheon_assurance": assurance}})

    assert done["answer_generation"] == {
        "mode": "legacy_unattributed",
        "model_identity": None,
        "model_family": None,
    }
    assert done["pantheon_evaluator_models"] == []


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
    assurance = _assurance()
    assurance["answer_generation"] = {
        "mode": "semantic_model",
        "model_identity": "narrator-gpt-5-4-mini",
        "model_family": None,
    }
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
            "pantheon_assurance": assurance,
        },
        "evidence_digest": "sha256:" + ("c" * 64),
        "semantic_result": _semantic_fallback(),
    }

    await consumer.consume(projection)

    assert store.projection is not None
    assert store.projection["status"] == "held"
