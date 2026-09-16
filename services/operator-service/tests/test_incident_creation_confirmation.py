"""Focused confirmation checks for semantic Incident creation drafts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, uuid5

import pytest
from fdai_operator_service.action_confirmation_runtime import ActionConfirmationOutboxDrainer
from fdai_operator_service.families.conversation import (
    ActionConfirmationBody,
    ConversationBoundaryError,
    PrincipalScope,
)
from fdai_operator_service.incident_creation_confirmation import (
    IncidentCreationConfirmationService,
    incident_creation_request_from_claim,
)
from fdai_operator_service.postgres_family_store import (
    ActionProposalClaim,
    PostgresFamilyStore,
    StoredProposal,
)
from fdai_service_contracts import OperatorPrincipalKind
from fdai_service_contracts.incident_creation import (
    INCIDENT_CREATION_REQUEST_TOPIC,
    IncidentCreationArguments,
    IncidentCreationDraft,
    IncidentCreationIntent,
    IncidentCreationRequest,
    build_incident_creation_draft,
)

NOW = datetime(2026, 9, 16, 2, 5, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
REQUEST_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.request"))
PROJECTION_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.projection"))


def _draft() -> IncidentCreationDraft:
    return build_incident_creation_draft(
        intent=IncidentCreationIntent(
            arguments=IncidentCreationArguments(severity="sev2", target="service-api"),
            source_input_digest=DIGEST,
        ),
        session_id="session-one",
        idempotency_key="draft-one",
        prepared_at=NOW,
    )


def _source() -> dict[str, object]:
    draft = _draft()
    return {
        "request_id": REQUEST_ID,
        "projection_id": PROJECTION_ID,
        "correlation_id": f"semantic-turn:{REQUEST_ID}",
        "idempotency_key": draft.idempotency_key,
        "status": "action_draft",
        "payload": {"incident_creation_draft": draft.model_dump(mode="json")},
        "semantic_result": {
            "disposition": "action_draft",
            "session_id": draft.session_id,
            "assurance_observation": {
                "frame": {"input_digest": draft.source_input_digest},
            },
        },
    }


def _body(**overrides: object) -> ActionConfirmationBody:
    values: dict[str, object] = {
        "action_type": "incident.create",
        "arguments": {"severity": "sev2", "target": "service-api"},
        "session_id": "session-one",
        "idempotency_key": "draft-one",
    }
    values.update(overrides)
    return ActionConfirmationBody.model_validate(values)


class _Store:
    def __init__(self, source: dict[str, object] | None = None) -> None:
        self.source = source
        self.appended: list[dict[str, object]] = []
        self.claim: ActionProposalClaim | None = None
        self.stored: StoredProposal | None = None
        self.marked: list[tuple[str, str]] = []
        self.rejected: list[tuple[str, str, str]] = []

    async def read_semantic_action_draft_by_key(self, **kwargs: object):
        assert self.source is not None
        assert kwargs == {
            "principal_id": "operator-one",
            "idempotency_key": self.source["idempotency_key"],
        }
        return self.source

    async def append_proposal(self, **kwargs: object) -> StoredProposal:
        self.appended.append(dict(kwargs))
        if self.stored is not None:
            return StoredProposal(
                proposal_id=self.stored.proposal_id,
                accepted_at=self.stored.accepted_at,
                duplicate=True,
                record=self.stored.record,
            )
        accepted_at = kwargs["accepted_at"]
        assert isinstance(accepted_at, datetime)
        record = {
            "family": kwargs["family"],
            "operation": kwargs["operation"],
            "principal_id": kwargs["principal_id"],
            "idempotency_key": kwargs["idempotency_key"],
            "payload": kwargs["payload"],
            "dispatch_status": "pending",
        }
        self.stored = StoredProposal(
            proposal_id="operator-proposal-one",
            accepted_at=accepted_at.isoformat(),
            duplicate=False,
            record=record,
        )
        return self.stored

    async def read_proposal(self, **kwargs: object) -> StoredProposal | None:
        if self.stored is None:
            return None
        assert kwargs == {
            "family": "conversation",
            "idempotency_key": self.stored.record["idempotency_key"],
        }
        return StoredProposal(
            proposal_id=self.stored.proposal_id,
            accepted_at=self.stored.accepted_at,
            duplicate=True,
            record=self.stored.record,
        )

    async def claim_action_proposal(self, **kwargs: object) -> ActionProposalClaim | None:
        assert kwargs == {"worker_id": "operator-action-confirmation", "lease_seconds": 120}
        claim, self.claim = self.claim, None
        return claim

    async def read_semantic_action_draft_source(self, **kwargs: object):
        assert kwargs == {
            "principal_id": "operator-one",
            "request_id": REQUEST_ID,
            "projection_id": PROJECTION_ID,
        }
        return self.source

    async def mark_action_proposal_published(self, *, key: str, claim_id: str) -> bool:
        self.marked.append((key, claim_id))
        return True

    async def mark_action_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool:
        self.rejected.append((key, claim_id, reason_code))
        return True

    async def release_action_proposal_claim(self, **_kwargs: object) -> bool:
        return True


class _Publisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, dict[str, object]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        self.messages.append((topic, key, dict(payload)))
        return object()


async def test_confirmation_reloads_and_persists_the_exact_server_draft() -> None:
    store = _Store(_source())
    service = IncidentCreationConfirmationService(
        store=cast(PostgresFamilyStore, store),
        clock=lambda: NOW + timedelta(minutes=1),
    )

    receipt = await service.confirm(
        scope=PrincipalScope(
            subject_id="operator-one",
            roles=frozenset({"Contributor"}),
            principal_kind=OperatorPrincipalKind.HUMAN,
        ),
        body=_body(),
    )

    assert receipt.response.status_code == 202
    assert receipt.response.body is not None
    assert receipt.response.body["submitted"] is True
    assert receipt.response.body["created"] is False
    persisted = store.appended[0]
    assert persisted["operation"] == "chat.action.confirm"
    payload = persisted["payload"]
    assert isinstance(payload, dict)
    assert payload["principal_roles"] == ["Contributor"]
    persisted_body = payload["body"]
    assert isinstance(persisted_body, dict)
    assert persisted_body["request_id"] == REQUEST_ID
    assert persisted_body["projection_id"] == PROJECTION_ID
    assert persisted["accepted_at"] == NOW + timedelta(minutes=1)


async def test_confirmation_rejects_tampering_and_expiry() -> None:
    store = _Store(_source())
    service = IncidentCreationConfirmationService(
        store=cast(PostgresFamilyStore, store),
        clock=lambda: NOW + timedelta(minutes=11),
    )

    with pytest.raises(ConversationBoundaryError) as mismatch:
        await service.confirm(
            scope=PrincipalScope("operator-one", frozenset({"Contributor"})),
            body=_body(arguments={"severity": "sev1", "target": "service-api"}),
        )
    assert mismatch.value.status_code == 409

    with pytest.raises(ConversationBoundaryError) as expired:
        await service.confirm(
            scope=PrincipalScope("operator-one", frozenset({"Contributor"})),
            body=_body(),
        )
    assert expired.value.status_code == 409
    assert store.appended == []


async def test_confirmation_retry_after_expiry_replays_the_original_acceptance() -> None:
    store = _Store(_source())
    accepted = IncidentCreationConfirmationService(
        store=cast(PostgresFamilyStore, store),
        clock=lambda: NOW + timedelta(minutes=9),
    )
    retried = IncidentCreationConfirmationService(
        store=cast(PostgresFamilyStore, store),
        clock=lambda: NOW + timedelta(minutes=11),
    )

    first = await accepted.confirm(
        scope=PrincipalScope("operator-one", frozenset({"Contributor"})),
        body=_body(),
    )
    second = await retried.confirm(
        scope=PrincipalScope("operator-one", frozenset({"Contributor"})),
        body=_body(),
    )

    assert first.response.status_code == second.response.status_code == 202
    assert first.response.body is not None and first.response.body["duplicate"] is False
    assert second.response.body is not None and second.response.body["duplicate"] is True
    assert first.response.body["accepted_at"] == second.response.body["accepted_at"]
    assert len(store.appended) == 1


async def test_drainer_publishes_versioned_incident_request_to_dedicated_topic() -> None:
    source = _source()
    draft = _draft()
    store = _Store(source)
    store.claim = ActionProposalClaim(
        key="operator-proposal:conversation:draft-one",
        claim_id="claim-one",
        principal_id="operator-one",
        payload={
            "idempotency_key": "draft-one",
            "principal_roles": ["Contributor"],
            "principal_kind": "human",
            "body": {
                **_body().model_dump(mode="json"),
                "request_id": REQUEST_ID,
                "projection_id": PROJECTION_ID,
                "incident_creation_draft": draft.model_dump(mode="json"),
            },
        },
        accepted_at=(NOW + timedelta(minutes=1)).isoformat(),
        attempt=1,
    )
    publisher = _Publisher()
    drainer = ActionConfirmationOutboxDrainer(
        store=cast(PostgresFamilyStore, store),
        publisher=publisher,
        topic="fdai.events",
    )

    assert await drainer.run_once() is True

    topic, key, payload = publisher.messages[0]
    assert topic == INCIDENT_CREATION_REQUEST_TOPIC
    request = IncidentCreationRequest.model_validate(payload)
    assert key == request.target_ref
    assert request.arguments.target == "service-api"
    assert request.execution_authority is False
    assert store.marked == [("operator-proposal:conversation:draft-one", "claim-one")]
    assert store.rejected == []


def test_drainer_uses_the_exact_durable_acceptance_time() -> None:
    draft = _draft()
    accepted_at = NOW + timedelta(minutes=9)
    claim = ActionProposalClaim(
        key="operator-proposal:conversation:draft-one",
        claim_id="claim-one",
        principal_id="operator-one",
        payload={
            "idempotency_key": "draft-one",
            "principal_roles": ["Contributor"],
            "principal_kind": "human",
            "body": {
                **_body().model_dump(mode="json"),
                "request_id": REQUEST_ID,
                "projection_id": PROJECTION_ID,
                "incident_creation_draft": draft.model_dump(mode="json"),
            },
        },
        accepted_at=accepted_at.isoformat(),
        attempt=1,
    )

    request = incident_creation_request_from_claim(
        claim,
        source_projection=_source(),
    )

    assert request.confirmed_at == accepted_at
