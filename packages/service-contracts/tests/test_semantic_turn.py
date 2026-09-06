"""Semantic-turn wire-contract integrity tests."""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai_service_contracts import (
    GoalTaskReceipt,
    RuleSearchProjection,
    RuleSearchReceipt,
    SemanticAssuranceObservation,
    SemanticInvestigationContinuation,
    SemanticTurnPrincipal,
    SemanticTurnRequest,
    SemanticTurnResult,
    OperatorRole,
    query_content_digest,
    rule_search_query_digest,
)
from pydantic import ValidationError


def test_empty_principal_groups_are_omitted_for_legacy_serialization() -> None:
    now = datetime(2026, 9, 6, tzinfo=UTC)
    request = SemanticTurnRequest(
        utterance="Show current evidence.",
        principal=SemanticTurnPrincipal(
            subject_id="operator-a",
            roles=(OperatorRole.READER,),
        ),
        session_id="session-a",
        turn_id="turn-a",
        turn_sequence=0,
        locale="en",
        purpose="operations-review",
        deadline_at=now + timedelta(seconds=30),
    )

    principal = request.model_dump(mode="json")["principal"]
    assert isinstance(principal, dict)
    assert "groups" not in principal


def _projection_payload() -> dict[str, Any]:
    query_digest = rule_search_query_digest(
        {
            "query": "find retry rules",
            "operation": "discover",
            "corpus": "active",
            "limit": 7,
        }
    )
    retrieval_receipt = RuleSearchReceipt.model_validate(
        {
            "schema_version": "1.0.0",
            "query_digest": query_digest,
            "operation": "discover",
            "corpus": "active",
            "catalog_digest": f"sha256:{'c' * 64}",
            "semantic_state": "available",
            "generation_digest": f"sha256:{'d' * 64}",
            "results": [],
            "execution_authority": False,
        }
    )
    invocation_receipt = GoalTaskReceipt.model_validate(
        {
            "task_id": "query:rules",
            "goal_id": "rules",
            "intent": "function",
            "capability": "query.function",
            "evidence_mode": "operational",
            "status": "completed",
            "duration_ms": 5,
            "evidence_refs": ["catalog:rule.one"],
            "started_at": "2026-08-11T00:00:00Z",
            "completed_at": "2026-08-11T00:00:00Z",
        }
    )
    invocation_payload = invocation_receipt.model_dump(mode="json")
    return {
        "query_digest": query_digest,
        "retrieval_receipt_digest": retrieval_receipt.digest,
        "function_invocation_receipt_digest": query_content_digest(invocation_payload),
        "candidates": [],
        "retrieval_receipt": retrieval_receipt.model_dump(mode="json"),
        "function_invocation_receipt": invocation_payload,
        "authority": "candidate_only",
        "execution_authority": False,
    }


def test_rule_search_projection_accepts_exact_function_invocation_receipt() -> None:
    projection = RuleSearchProjection.model_validate(_projection_payload())

    assert projection.function_invocation_receipt.task_id == "query:rules"
    assert projection.execution_authority is False


@pytest.mark.parametrize(
    "tamper",
    (
        lambda payload: payload.__setitem__(
            "function_invocation_receipt_digest", f"sha256:{'0' * 64}"
        ),
        lambda payload: payload["function_invocation_receipt"].__setitem__("duration_ms", 6),
    ),
    ids=("digest", "content"),
)
def test_rule_search_projection_rejects_function_receipt_digest_tampering(
    tamper: Callable[[dict[str, Any]], None],
) -> None:
    payload = copy.deepcopy(_projection_payload())
    tamper(payload)

    with pytest.raises(ValidationError, match="digest MUST match canonical"):
        RuleSearchProjection.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "failed"),
        ("task_id", "query:other"),
        ("intent", "relationship"),
        ("capability", "query.relationship"),
    ),
)
def test_rule_search_projection_rejects_non_function_invocation_receipts(
    field: str,
    value: str,
) -> None:
    payload = copy.deepcopy(_projection_payload())
    invocation_receipt = payload["function_invocation_receipt"]
    invocation_receipt[field] = value
    payload["function_invocation_receipt_digest"] = query_content_digest(invocation_receipt)

    with pytest.raises(ValidationError, match="completed query function"):
        RuleSearchProjection.model_validate(payload)


def _semantic_result_payload() -> dict[str, Any]:
    return {
        "disposition": "held",
        "reason_code": "semantic_runtime_unavailable",
        "unavailable_reason": "semantic_planner_unavailable",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "execution_authority": False,
    }


def _continuation_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "source_session_id": "session-1",
        "source_turn_id": "turn-1",
        "source_turn_sequence": 1,
        "target_type": "BusinessService",
        "target_value": "service-example-api",
        "recovery_measure_concepts": ["dependency.latency", "service.latency"],
        "baseline_start": "2026-08-26T00:00:00Z",
        "baseline_end": "2026-08-26T00:10:00Z",
        "initial_observation_cutoff": "2026-08-26T00:20:00Z",
        "ontology_release_digest": f"sha256:{'a' * 64}",
        "principal_manifest_digest": f"sha256:{'b' * 64}",
        "source_frame_digest": f"sha256:{'c' * 64}",
        "source_plan_digest": f"sha256:{'d' * 64}",
        "source_execution_receipt_digest": f"sha256:{'e' * 64}",
        "execution_authority": False,
    }


def test_semantic_investigation_continuation_accepts_ordered_verified_context() -> None:
    continuation = SemanticInvestigationContinuation.model_validate(_continuation_payload())

    assert continuation.target_type == "BusinessService"
    assert continuation.execution_authority is False


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.__setitem__(
            "recovery_measure_concepts", ["service.latency", "dependency.latency"]
        ),
        lambda payload: payload.__setitem__("baseline_end", "2026-08-25T23:59:00Z"),
        lambda payload: payload.__setitem__("baseline_start", "2026-08-26T00:00:00"),
        lambda payload: payload.__setitem__("execution_authority", True),
    ),
    ids=("unordered-measures", "reversed-window", "naive-time", "authority"),
)
def test_semantic_investigation_continuation_rejects_invalid_context(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    payload = _continuation_payload()
    mutation(payload)

    with pytest.raises(ValidationError):
        SemanticInvestigationContinuation.model_validate(payload)


def test_semantic_result_accepts_typed_unavailability() -> None:
    result = SemanticTurnResult.model_validate(_semantic_result_payload())

    assert result.semantic_route is None
    assert result.unavailable_reason == "semantic_planner_unavailable"


def test_semantic_result_accepts_evidence_free_direct_greeting() -> None:
    payload = {
        "disposition": "direct_response",
        "reason_code": "semantic_direct_response",
        "semantic_route": "semantic_direct_response",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "answer": "Hello. What would you like to inspect?",
        "direct_response_intent": "greeting",
        "execution_authority": False,
    }

    result = SemanticTurnResult.model_validate(payload)

    assert result.direct_response_intent == "greeting"
    assert result.evidence_refs == ()


def test_semantic_result_accepts_evidence_free_self_introduction() -> None:
    payload = {
        "disposition": "direct_response",
        "reason_code": "semantic_direct_response",
        "semantic_route": "semantic_direct_response",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "answer": "I am Bragi, the FDAI Console conversation interface.",
        "direct_response_intent": "self_introduction",
        "execution_authority": False,
    }

    result = SemanticTurnResult.model_validate(payload)

    assert result.direct_response_intent == "self_introduction"
    assert result.evidence_refs == ()


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.pop("direct_response_intent"),
        lambda payload: payload.update({"evidence_refs": ["ontology:unexpected"]}),
        lambda payload: payload.update({"plan_digest": f"sha256:{'a' * 64}"}),
    ),
    ids=("missing-intent", "evidence", "query-digest"),
)
def test_semantic_result_rejects_invalid_direct_response(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    payload = {
        "disposition": "direct_response",
        "reason_code": "semantic_direct_response",
        "semantic_route": "semantic_direct_response",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "answer": "Hello. What would you like to inspect?",
        "direct_response_intent": "greeting",
        "execution_authority": False,
    }
    mutation(payload)

    with pytest.raises(ValidationError, match="direct response semantic results"):
        SemanticTurnResult.model_validate(payload)


def _assurance_observation_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "frame": {
            "operation": "select",
            "subject_types": ["Incident"],
            "measure_concepts": [],
            "temporal_scope": "current",
            "output_shape": "incident_evidence",
            "frame_digest": f"sha256:{'a' * 64}",
        },
        "capabilities": ["incident_evidence"],
        "object_types": ["Incident"],
        "link_types": [],
        "function_types": ["query.incident_evidence"],
        "ontology_paths": [],
        "fact_kinds": ["incident.evidence"],
        "limitation_kinds": ["incident_evidence_gaps_must_be_preserved"],
        "claim_kinds": [],
        "evidence_posture": "incomplete",
        "authority_posture": "read_only",
        "read_performed": True,
        "execution_authority": False,
    }
    payload["observation_digest"] = query_content_digest(payload)
    return payload


def test_semantic_assurance_observation_accepts_content_addressed_typed_axes() -> None:
    observation = SemanticAssuranceObservation.model_validate(_assurance_observation_payload())

    assert observation.fact_kinds == ("incident.evidence",)
    assert observation.execution_authority is False


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload["capabilities"].extend(["incident_evidence"]),
        lambda payload: payload.__setitem__("observation_digest", f"sha256:{'0' * 64}"),
    ),
    ids=("duplicate-axis", "digest-mismatch"),
)
def test_semantic_assurance_observation_rejects_noncanonical_content(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    payload = _assurance_observation_payload()
    mutation(payload)

    with pytest.raises(ValidationError, match="semantic assurance"):
        SemanticAssuranceObservation.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.pop("unavailable_reason"),
        lambda payload: payload.update({"semantic_route": "verified_query_plan"}),
        lambda payload: payload.update(
            {
                "disposition": "unsupported",
                "semantic_route": "semantic_clarification",
            }
        ),
    ),
    ids=("missing", "both", "route-mismatch"),
)
def test_semantic_result_rejects_ambiguous_terminal_routing(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    payload = _semantic_result_payload()
    mutation(payload)

    with pytest.raises(ValidationError, match="semantic result"):
        SemanticTurnResult.model_validate(payload)
