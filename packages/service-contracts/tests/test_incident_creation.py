from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
from fdai_service_contracts.incident_creation import (
    IncidentCreationArguments,
    IncidentCreationConfirmationBody,
    IncidentCreationDraft,
    IncidentCreationIntent,
    IncidentCreationRequest,
    build_incident_creation_draft,
    build_incident_creation_request,
    incident_creation_target_ref,
)
from fdai_service_contracts.operator import OperatorRole
from pydantic import ValidationError

NOW = datetime(2026, 9, 16, 2, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
SOURCE_REQUEST_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.request"))
SOURCE_PROJECTION_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.projection"))


def _intent() -> IncidentCreationIntent:
    return IncidentCreationIntent(
        arguments=IncidentCreationArguments(severity="sev2", target="resource:service/api"),
        source_input_digest=DIGEST,
    )


def _draft() -> IncidentCreationDraft:
    return build_incident_creation_draft(
        intent=_intent(),
        session_id="session-one",
        idempotency_key="draft-one",
        prepared_at=NOW,
    )


def test_draft_is_candidate_only_and_expires_within_the_fixed_window() -> None:
    draft = _draft()

    assert draft.action_type == "incident.create"
    assert draft.arguments.severity == "sev2"
    assert draft.expires_at - draft.prepared_at == timedelta(minutes=10)
    assert draft.authority == "candidate_only"
    assert draft.execution_authority is False


def test_confirmation_rejects_unknown_fields_and_modified_arguments() -> None:
    with pytest.raises(ValidationError):
        IncidentCreationConfirmationBody.model_validate(
            {
                "action_type": "incident.create",
                "arguments": {"severity": "sev2", "target": "resource:service/api"},
                "session_id": "session-one",
                "idempotency_key": "draft-one",
                "principal_id": "browser-supplied",
            }
        )
    with pytest.raises(ValidationError):
        IncidentCreationConfirmationBody.model_validate(
            {
                "action_type": "incident.create",
                "arguments": {"severity": "sev2", "target": "service|api"},
                "session_id": "session-one",
                "idempotency_key": "draft-one",
            }
        )
    with pytest.raises(ValidationError):
        IncidentCreationConfirmationBody.model_validate(
            {
                "action_type": "incident.create",
                "arguments": {"severity": "critical", "target": "resource:service/api"},
                "session_id": "session-one",
                "idempotency_key": "draft-one",
            }
        )


def test_draft_rejects_expiry_or_content_change_without_digest_change() -> None:
    draft = _draft()
    values = draft.model_dump(mode="json")

    with pytest.raises(ValidationError):
        IncidentCreationDraft.model_validate(
            {**values, "expires_at": (NOW + timedelta(minutes=11)).isoformat()}
        )
    with pytest.raises(ValidationError):
        IncidentCreationDraft.model_validate(
            {
                **values,
                "arguments": {"severity": "sev1", "target": "resource:service/api"},
            }
        )


def test_request_is_human_contributor_scoped_and_digest_bound() -> None:
    draft = _draft()
    request = build_incident_creation_request(
        request_id="operator-request-one",
        source_request_id=SOURCE_REQUEST_ID,
        source_projection_id=SOURCE_PROJECTION_ID,
        principal_id="operator-one",
        principal_roles=(OperatorRole.CONTRIBUTOR,),
        idempotency_key=draft.idempotency_key,
        session_id=draft.session_id,
        arguments=draft.arguments,
        source_input_digest=draft.source_input_digest,
        draft_digest=draft.draft_digest,
        draft_expires_at=draft.expires_at,
        confirmed_at=NOW + timedelta(minutes=1),
    )

    assert request.target_ref == incident_creation_target_ref("resource:service/api")
    assert request.execution_authority is False
    with pytest.raises(ValidationError):
        IncidentCreationRequest.model_validate(
            {**request.model_dump(mode="json"), "principal_roles": ["Reader"]}
        )
    with pytest.raises(ValidationError):
        IncidentCreationRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "principal_roles": ["Contributor", "BreakGlass"],
            }
        )
    with pytest.raises(ValidationError):
        IncidentCreationRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "arguments": {"severity": "sev1", "target": "resource:service/api"},
            }
        )
