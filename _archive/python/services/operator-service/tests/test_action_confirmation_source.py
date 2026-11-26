"""Focused source-binding checks for generic semantic action confirmation."""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from fdai_operator_service.action_confirmation_source import (
    validate_browser_action_confirmation,
)
from fdai_operator_service.families.conversation import (
    ActionConfirmationBody,
    PrincipalScope,
)
from fdai_operator_service.incident_creation_confirmation import (
    IncidentCreationConfirmationService,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    StoredProposal,
)
from fdai_service_contracts import query_content_digest
from fdai_service_contracts.action_intent import ActionIntentSource, OntologyActionIntent

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 9, 16, 2, 5, tzinfo=UTC)
REQUEST_ID = str(uuid5(NAMESPACE_URL, "fdai.test.action-confirmation.request"))
PROJECTION_ID = str(uuid5(NAMESPACE_URL, "fdai.test.action-confirmation.projection"))


def _intent() -> OntologyActionIntent:
    arguments = {"replicas": 3, "target_resource_ref": "resource:service/api"}
    target_selector = {"resource_ref": "resource:service/api"}
    material = {
        "schema_version": "1.0.0",
        "source": "operator_language",
        "actor_ref": "operator:operator-one",
        "purpose": "operations-review",
        "ontology_release_digest": DIGEST,
        "action_type_name": "ops.scale-out",
        "action_type_version": "1.0.0",
        "action_declaration_digest": "sha256:" + "b" * 64,
        "arguments": arguments,
        "target_selector": target_selector,
        "evidence_refs": ("semantic-frame:one",),
        "input_digest": "sha256:" + "c" * 64,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    return OntologyActionIntent(
        source=ActionIntentSource.OPERATOR_LANGUAGE,
        actor_ref="operator:operator-one",
        purpose="operations-review",
        ontology_release_digest=DIGEST,
        action_type_name="ops.scale-out",
        action_type_version="1.0.0",
        action_declaration_digest="sha256:" + "b" * 64,
        arguments_json='{"replicas":3,"target_resource_ref":"resource:service/api"}',
        target_selector_json='{"resource_ref":"resource:service/api"}',
        evidence_refs=("semantic-frame:one",),
        input_digest="sha256:" + "c" * 64,
        intent_digest=query_content_digest(material),
    )


def test_generic_action_confirmation_matches_server_owned_intent() -> None:
    intent = _intent()
    body = ActionConfirmationBody(
        action_type=intent.action_type_name,
        arguments=intent.arguments,
        session_id="session-one",
        idempotency_key="draft-action",
    )
    source = {
        "idempotency_key": body.idempotency_key,
        "status": "action_draft",
        "semantic_result": {
            "disposition": "action_draft",
            "session_id": body.session_id,
            "action_intent": intent.model_dump(mode="json"),
        },
    }

    assert (
        validate_browser_action_confirmation(
            body,
            source,
            principal_id="operator-one",
        )
        == intent
    )


async def test_generic_confirmation_does_not_apply_incident_expiry() -> None:
    intent = _intent()
    source = {
        "request_id": REQUEST_ID,
        "projection_id": PROJECTION_ID,
        "correlation_id": "semantic-turn:request-one",
        "idempotency_key": "draft-action",
        "status": "action_draft",
        "recorded_at": NOW.isoformat(),
        "payload": {},
        "semantic_result": {
            "disposition": "action_draft",
            "session_id": "session-one",
            "action_intent": intent.model_dump(mode="json"),
        },
    }

    class _Store:
        appended: dict[str, object] | None = None

        async def read_semantic_action_draft_by_key(self, **_kwargs: object):
            return source

        async def append_proposal(self, **kwargs: object) -> StoredProposal:
            self.appended = dict(kwargs)
            accepted_at = kwargs["accepted_at"]
            assert isinstance(accepted_at, datetime)
            return StoredProposal(
                "operator-proposal-one",
                accepted_at.isoformat(),
                False,
                {"dispatch_status": "pending"},
            )

    store = _Store()
    service = IncidentCreationConfirmationService(
        store=cast(PostgresFamilyStore, store),
        clock=lambda: NOW + timedelta(days=1),
    )
    body = ActionConfirmationBody(
        action_type="ops.scale-out",
        arguments=intent.arguments,
        session_id="session-one",
        idempotency_key="draft-action",
    )

    receipt = await service.confirm(
        scope=PrincipalScope("operator-one", frozenset({"Contributor"})),
        body=body,
    )

    assert receipt.response.status_code == 202
    assert store.appended is not None
    payload = store.appended["payload"]
    assert isinstance(payload, dict)
    stored_body = payload["body"]
    assert isinstance(stored_body, dict)
    assert stored_body["ontology_intent"] == intent.model_dump(mode="json")
