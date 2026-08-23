"""Focused checks for the read-investigation request wire contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fdai_service_contracts.read_investigation import (
    ReadInvestigationCancellation,
    ReadInvestigationIntent,
    ReadInvestigationOrigin,
    ReadInvestigationProposalBody,
    ReadInvestigationRequest,
    ReadInvestigationSelector,
    ReadInvestigationTaskBudget,
    build_read_investigation_cancellation,
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
