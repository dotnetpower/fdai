from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fdai_service_contracts.incident_intervention import (
    IncidentExceptionDuration,
    IncidentInterventionAction,
    IncidentInterventionProposalBody,
    IncidentInterventionRequest,
    build_incident_intervention_request,
    incident_target_ref,
)
from fdai_service_contracts.operator import OperatorRole

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
INCIDENT_ID = "00000000-0000-0000-0000-000000000123"
TARGET_REF = incident_target_ref("service:checkout-api")


def _body(**overrides: object) -> IncidentInterventionProposalBody:
    values: dict[str, object] = {
        "action": "operator_guidance",
        "incident_id": INCIDENT_ID,
        "correlation_id": "incident-correlation-1",
        "expected_state": "triaging",
        "comment": "Keep the development context for the next decision.",
    }
    values.update(overrides)
    return IncidentInterventionProposalBody.model_validate(values)


def test_public_body_rejects_unknown_and_action_inconsistent_fields() -> None:
    with pytest.raises(ValidationError):
        _body(unknown=True)
    with pytest.raises(ValidationError):
        _body(duration="one_day")
    with pytest.raises(ValidationError):
        _body(action="create_development_exception")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("incident_id", "000000000-0000-0000-0000-000000000000"),
        ("exception_id", "0000000-00000-0000-0000-000000000000"),
        ("comment", "Expected development activity.\u202eHidden direction"),
        ("comment", "Expected\u200bdevelopment activity."),
    ],
)
def test_public_body_rejects_noncanonical_identity_and_visual_controls(
    field: str,
    value: str,
) -> None:
    values = _body(
        action=IncidentInterventionAction.REVOKE_DEVELOPMENT_EXCEPTION,
        exception_id="00000000-0000-0000-0000-000000000010",
    ).model_dump()
    values[field] = value

    with pytest.raises(ValidationError):
        IncidentInterventionProposalBody.model_validate(values)


@pytest.mark.parametrize(
    ("duration", "role", "accepted"),
    [
        ("one_day", OperatorRole.CONTRIBUTOR, False),
        ("one_week", OperatorRole.APPROVER, True),
        ("one_month", OperatorRole.OWNER, True),
        ("until_revoked", OperatorRole.APPROVER, False),
        ("until_revoked", OperatorRole.OWNER, True),
    ],
)
def test_create_exception_role_floor_is_digest_bound(
    duration: str,
    role: OperatorRole,
    accepted: bool,
) -> None:
    body = _body(
        action=IncidentInterventionAction.CREATE_DEVELOPMENT_EXCEPTION,
        duration=IncidentExceptionDuration(duration),
    )

    def build() -> IncidentInterventionRequest:
        return build_incident_intervention_request(
            request_id="operator-request-1",
            principal_id="operator-1",
            principal_roles=(role,),
            idempotency_key="idempotency-1",
            target_ref=TARGET_REF,
            body=body,
            requested_at=NOW,
        )

    if accepted:
        assert build().execution_authority is False
    else:
        with pytest.raises(ValidationError):
            build()


def test_request_rejects_content_change_without_digest_change() -> None:
    request = build_incident_intervention_request(
        request_id="operator-request-1",
        principal_id="operator-1",
        principal_roles=(OperatorRole.CONTRIBUTOR,),
        idempotency_key="idempotency-1",
        target_ref=TARGET_REF,
        body=_body(),
        requested_at=NOW,
    )

    with pytest.raises(ValidationError):
        IncidentInterventionRequest.model_validate(
            {**request.model_dump(mode="json"), "comment": "Changed after acceptance."}
        )


def test_target_ref_is_exact_bounded_and_non_reversible() -> None:
    first = incident_target_ref("/subscriptions/example/resourceGroups/one")

    assert first.startswith("sha256:")
    assert first != incident_target_ref("/subscriptions/example/resourceGroups/two")
    assert "/subscriptions/" not in first
    with pytest.raises(ValueError):
        incident_target_ref("")
