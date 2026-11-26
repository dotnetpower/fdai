"""Focused checks for the read-investigation request wire contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.read_investigation import (
    ReadInvestigationCancellation,
    ReadInvestigationCompletion,
    ReadInvestigationCompletionUsage,
    ReadInvestigationIntent,
    ReadInvestigationOrigin,
    ReadInvestigationProposalBody,
    ReadInvestigationRequest,
    ReadInvestigationSelector,
    ReadInvestigationTaskBudget,
    build_read_investigation_cancellation,
    build_read_investigation_completion,
    build_read_investigation_request,
    read_investigation_task_id,
)


def _request(**updates: object) -> ReadInvestigationRequest:
    origin = ReadInvestigationOrigin(
        conversation_id="conversation-one",
        channel_kind="operator-api",
        channel_id="principal-one",
    )
    values: dict[str, object] = {
        "request_id": "operator-request-one",
        "owner_principal_id": "principal-one",
        "idempotency_key": "idempotency-one",
        "correlation_id": "correlation-one",
        "prompt": "Inspect the current resource state",
        "intent": ReadInvestigationIntent.RESOURCE_STATE,
        "selector": ReadInvestigationSelector(name="service-one"),
        "origin": origin,
        "budget": ReadInvestigationTaskBudget(),
        "explicit_deep": False,
        "requested_at": datetime(2026, 8, 23, tzinfo=UTC),
    }
    values.update(updates)
    return build_read_investigation_request(**values)  # type: ignore[arg-type]


def test_request_round_trips_with_no_execution_authority() -> None:
    request = _request()

    restored = ReadInvestigationRequest.model_validate_json(request.model_dump_json())

    assert restored == request
    assert restored.accountable_agent == "Heimdall"
    assert restored.capability_profile_id == "background.read-only"
    assert restored.execution_authority is False
    assert (
        len(
            read_investigation_task_id(
                restored.owner_principal_id,
                restored.idempotency_key,
            )
        )
        == 43
    )


def test_request_rejects_tampered_content() -> None:
    request = _request()

    with pytest.raises(ValidationError, match="digest does not match"):
        ReadInvestigationRequest.model_validate(
            {**request.model_dump(mode="json"), "prompt": "Different prompt"}
        )


def test_request_rejects_naive_time_and_unknown_fields() -> None:
    request = _request()

    with pytest.raises(ValidationError, match="timezone-aware"):
        _request(requested_at=datetime(2026, 8, 23))
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReadInvestigationRequest.model_validate(
            {**request.model_dump(mode="json"), "provider_query": "Resources | take 1"}
        )


def test_request_rejects_unknown_intent_and_unbounded_selector_fields() -> None:
    request = _request()

    with pytest.raises(ValueError):
        _request(intent="invented")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReadInvestigationRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "selector": {
                    "name": "service-one",
                    "subscription_id": "not-accepted",
                },
            }
        )


def test_request_rejects_oversized_prompt_and_budget() -> None:
    with pytest.raises(ValidationError):
        _request(prompt="x" * 4_001)
    with pytest.raises(ValidationError):
        ReadInvestigationTaskBudget(max_wall_seconds=3_601)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "line one\nline two"),
        ("resource_name", "service\x00one"),
        ("resource_type", "virtual\tmachine"),
        ("resource_group", "group\rone"),
    ],
)
def test_proposal_rejects_core_incompatible_control_characters(
    field: str,
    value: str,
) -> None:
    payload: dict[str, object] = {
        "prompt": "Inspect",
        "intent": "resource_state",
        "resource_name": "service-one",
    }
    payload[field] = value

    with pytest.raises(ValidationError, match="control characters"):
        ReadInvestigationProposalBody.model_validate(payload)


def test_cancellation_round_trips_and_rejects_tampering() -> None:
    cancellation = build_read_investigation_cancellation(
        request_id="cancel-one",
        owner_principal_id="principal-one",
        task_id="background-one",
        idempotency_key="cancel-idempotency",
        requested_at=datetime(2026, 8, 23, tzinfo=UTC),
        admin_override=False,
    )

    restored = ReadInvestigationCancellation.model_validate_json(cancellation.model_dump_json())
    assert restored == cancellation
    assert restored.execution_authority is False
    with pytest.raises(ValidationError, match="digest does not match"):
        ReadInvestigationCancellation.model_validate(
            {**cancellation.model_dump(mode="json"), "task_id": "background-other"}
        )


def _completion() -> ReadInvestigationCompletion:
    started_at = datetime(2026, 8, 26, tzinfo=UTC)
    return build_read_investigation_completion(
        task_id=read_investigation_task_id("principal-one", "idempotency-one"),
        attempt_id="attempt-one",
        attempt_number=1,
        owner_principal_id="principal-one",
        request_idempotency_key="idempotency-one",
        correlation_id="correlation-one",
        origin=ReadInvestigationOrigin(
            conversation_id="conversation-one",
            channel_kind="web",
            channel_id="principal-one",
        ),
        status="succeeded",
        terminal_reason="matched",
        summary="The resource is healthy.",
        evidence_refs=("evidence-one",),
        usage=ReadInvestigationCompletionUsage(tool_calls=1),
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1),
        completed_at=started_at + timedelta(seconds=2),
        retention_until=started_at + timedelta(days=30),
    )


def test_completion_round_trips_with_deterministic_no_authority_identity() -> None:
    completion = _completion()

    restored = ReadInvestigationCompletion.model_validate_json(completion.model_dump_json())

    assert restored == completion
    assert restored.schema_version == "1.0.0"
    assert restored.completion_id.startswith("read-completion-")
    assert restored.trusted is False
    assert restored.execution_authority is False


def test_completion_rejects_tampering_and_invalid_evidence_or_time() -> None:
    completion = _completion()
    values = {
        "task_id": completion.task_id,
        "attempt_id": completion.attempt_id,
        "attempt_number": completion.attempt_number,
        "owner_principal_id": completion.owner_principal_id,
        "request_idempotency_key": completion.request_idempotency_key,
        "correlation_id": completion.correlation_id,
        "origin": completion.origin,
        "status": completion.status,
        "terminal_reason": completion.terminal_reason,
        "summary": completion.summary,
        "evidence_refs": completion.evidence_refs,
        "usage": completion.usage,
        "started_at": completion.started_at,
        "finished_at": completion.finished_at,
        "completed_at": completion.completed_at,
        "retention_until": completion.retention_until,
    }

    with pytest.raises(ValidationError, match="digest does not match"):
        ReadInvestigationCompletion.model_validate(
            {**completion.model_dump(mode="json"), "summary": "tampered"}
        )
    with pytest.raises(ValidationError, match="evidence_refs MUST be unique"):
        build_read_investigation_completion(
            **{
                **values,
                "evidence_refs": ("evidence-one", "evidence-one"),
            }
        )
    with pytest.raises(ValidationError, match="timestamps MUST be ordered"):
        build_read_investigation_completion(
            **{
                **values,
                "retention_until": completion.completed_at - timedelta(seconds=1),
            }
        )
