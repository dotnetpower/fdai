"""Advisory answers cannot manufacture operational evidence or action authority."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from fdai_service_contracts import (
    AdaptiveAnswer,
    AdaptiveGoalResult,
    SemanticTurnDisposition,
    SemanticTurnResult,
)
from fdai_service_contracts.codec import ConsumerCodec, ProducerCodec
from fdai_service_contracts.compatibility import CompatibilityError
from fdai_service_contracts.schema import ContractValidationError
from fdai_service_contracts.translators import core_operator_projection_1_2_to_1_0


def _answer() -> dict[str, Any]:
    return {
        "answer": "An SLO is a measurable service objective.",
        "goals": [
            {"goal_id": "explain", "kind": "knowledge", "status": "answered", "required": True},
            {
                "goal_id": "example",
                "kind": "environment_example",
                "status": "unavailable",
                "required": False,
                "limitation": "No scoped environment evidence is available.",
            },
        ],
        "role_agent": "Bragi",
        "quality_status": "limited",
        "refinements": 0,
        "execution_authority": False,
    }


def _result() -> dict[str, Any]:
    adaptive = AdaptiveAnswer.model_validate(_answer())
    return SemanticTurnResult(
        disposition=SemanticTurnDisposition.ADVISORY_RESPONSE,
        reason_code="semantic_advisory_response",
        semantic_route="semantic_advisory_response",
        session_id="session-example",
        turn_id="turn-example",
        turn_sequence=1,
        answer=adaptive.answer,
        adaptive_answer=adaptive,
    ).model_dump(mode="json", exclude_none=True)


def _projection() -> dict[str, Any]:
    return {
        "schema_version": "1.6.0",
        "projection_id": "00000000-0000-0000-0000-000000000001",
        "request_id": "00000000-0000-0000-0000-000000000002",
        "correlation_id": "correlation-example",
        "idempotency_key": "advisory-example",
        "status": "advisory_response",
        "recorded_at": "2026-09-06T00:00:00Z",
        "payload": {},
        "semantic_result": _result(),
    }


def test_advisory_answer_is_immutable_and_round_trips_without_query_receipts() -> None:
    answer = AdaptiveAnswer.model_validate(_answer())
    with pytest.raises(ValidationError, match="frozen"):
        answer.answer = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        answer.goals[0].status = "held"
    producer = ProducerCodec("core-operator-projection", "N", "1.6.0")
    consumer = ConsumerCodec("core-operator-projection", "N", ("1.4.0", "1.6.0"))
    projection = _projection()
    assert consumer.decode(producer.encode(projection)) == projection
    assert "execution_receipt_digest" not in projection["semantic_result"]


def test_advisory_requires_an_accepting_consumer_and_cannot_masquerade_as_legacy() -> None:
    projection = _projection()
    encoded = ProducerCodec("core-operator-projection", "N", "1.6.0").encode(projection)
    with pytest.raises(CompatibilityError, match="rejects version"):
        ConsumerCodec("core-operator-projection", "previous", ("1.4.0",)).decode(encoded)
    with pytest.raises(CompatibilityError, match="cannot be downgraded"):
        core_operator_projection_1_2_to_1_0(projection)
    projection["schema_version"] = "1.4.0"
    with pytest.raises(ContractValidationError):
        ProducerCodec("core-operator-projection", "previous", "1.4.0").encode(projection)


def test_accepting_consumer_preserves_existing_action_draft_wire_shape() -> None:
    projection = _projection()
    projection.update(schema_version="1.4.0", status="action_draft")
    projection["semantic_result"] = SemanticTurnResult(
        disposition=SemanticTurnDisposition.ACTION_DRAFT,
        reason_code="semantic_action_draft",
        semantic_route="semantic_action_draft",
        session_id="session-example",
        turn_id="turn-example",
        turn_sequence=1,
        answer="Review the governed action draft.",
    ).model_dump(mode="json", exclude_none=True)
    encoded = ProducerCodec("core-operator-projection", "previous", "1.4.0").encode(projection)
    assert (
        ConsumerCodec("core-operator-projection", "N", ("1.4.0", "1.6.0")).decode(encoded)
        == projection
    )
    assert "adaptive_answer" not in projection["semantic_result"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("answer", " "),
        ("answer", "x" * 16_001),
        ("goals", []),
        ("role_agent", "Unregistered"),
        ("refinements", 2),
        ("refinements", True),
        ("execution_authority", True),
        ("execution_authority", 0),
    ],
)
def test_advisory_answer_rejects_unbounded_or_authority_bearing_values(
    field: str, value: object
) -> None:
    payload = _answer()
    payload[field] = value
    with pytest.raises(ValidationError):
        AdaptiveAnswer.model_validate(payload)


@pytest.mark.parametrize("kind", ["operational", "environment_example"])
def test_environment_goal_requires_real_support(kind: str) -> None:
    goal = {"goal_id": "example", "kind": kind, "status": "answered", "required": False}
    with pytest.raises(ValidationError, match="require verified evidence"):
        AdaptiveGoalResult.model_validate(goal)
    supported = AdaptiveGoalResult.model_validate(
        {**goal, "evidence_refs": ["inventory:verified-example"]}
    )
    assert supported.evidence_refs == ("inventory:verified-example",)


def test_advisory_goals_reject_misattributed_support_and_duplicate_ids() -> None:
    payload = _answer()
    payload["goals"][0]["evidence_refs"] = ["inventory:example"]
    with pytest.raises(ValidationError, match="general knowledge"):
        AdaptiveAnswer.model_validate(payload)
    payload = _answer()
    payload["goals"].append(copy.deepcopy(payload["goals"][0]))
    with pytest.raises(ValidationError, match="identifiers MUST be unique"):
        AdaptiveAnswer.model_validate(payload)
    payload["goals"] = [copy.deepcopy(payload["goals"][0]) for _ in range(9)]
    with pytest.raises(ValidationError):
        AdaptiveAnswer.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("answer", "A different answer"),
        ("execution_receipt_digest", "sha256:" + "a" * 64),
        ("evidence_refs", ["inventory:blanket-claim"]),
        ("checks_total", 1),
        ("adaptive_answer", None),
        ("disposition", "answered"),
    ],
)
def test_wire_rejects_advisory_whole_response_claims(field: str, value: object) -> None:
    payload = _projection()
    payload["semantic_result"][field] = value
    with pytest.raises(ContractValidationError):
        ProducerCodec("core-operator-projection", "N", "1.6.0").encode(payload)


def test_non_advisory_terminal_cannot_carry_adaptive_metadata() -> None:
    payload = _result()
    payload.update(
        disposition="direct_response",
        semantic_route="semantic_direct_response",
        direct_response_intent="greeting",
    )
    with pytest.raises(ValidationError, match="only advisory"):
        SemanticTurnResult.model_validate(payload)


def test_required_goal_failure_requires_limited_quality() -> None:
    payload = _answer()
    payload["goals"][1]["required"] = True
    payload["quality_status"] = "passed"
    with pytest.raises(ValidationError, match="limited answer quality"):
        AdaptiveAnswer.model_validate(payload)


def test_action_draft_can_keep_separate_advisory_explanation_without_replacing_draft_text() -> None:
    payload = _projection()
    payload["status"] = "action_draft"
    payload["semantic_result"].update(
        disposition="action_draft",
        reason_code="semantic_action_draft",
        semantic_route="semantic_action_draft",
        answer="Review this action draft before requesting execution.",
    )
    encoded = ProducerCodec("core-operator-projection", "N", "1.6.0").encode(payload)
    decoded = ConsumerCodec("core-operator-projection", "N", ("1.6.0",)).decode(encoded)
    assert decoded == payload
    assert (
        decoded["semantic_result"]["answer"]
        != decoded["semantic_result"]["adaptive_answer"]["answer"]
    )
    assert decoded["semantic_result"]["execution_authority"] is False
