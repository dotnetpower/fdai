from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.bus_poison_halt_clear import OrderedPoisonHaltClearService
from fdai_operator_service.conversation_family_adapters import UnavailableConversationAdapters
from fdai_operator_service.families.conversation import ConversationFamilyDependencies
from fdai_operator_service.family_adapters import (
    UnavailableOperationsAdapters,
    UnavailableWorkflowAdapters,
)
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_operator_service.iam_composition import build_unavailable_iam_bindings
from fdai_operator_service.routes import OperatorRouteFamilies, build_operator_app
from fdai_operator_service.streaming import LiveStreamHub
from fdai_service_contracts.bus_poison_halt_clear import ORDERED_POISON_HALT_CLEAR_TOPIC
from fdai_service_contracts.operator import (
    OperatorPrincipal,
    OperatorPrincipalKind,
    OperatorRole,
)
from starlette.testclient import TestClient


@dataclass(frozen=True, slots=True)
class _Stored:
    duplicate: bool


class _Store:
    def __init__(self) -> None:
        self.proposals: list[tuple[str, str, Mapping[str, object]]] = []

    async def append_proposal(self, **kwargs: object) -> object:
        existing = next(
            (
                proposal
                for proposal in self.proposals
                if proposal[1] == str(kwargs["idempotency_key"])
            ),
            None,
        )
        if existing is not None:
            return _Stored(duplicate=True)
        self.proposals.append(
            (
                str(kwargs["operation"]),
                str(kwargs["idempotency_key"]),
                kwargs["payload"],  # type: ignore[arg-type]
            )
        )
        return _Stored(duplicate=False)


class _Publisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Mapping[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        self.published.append((topic, key, payload))
        return object()


def _body() -> dict[str, object]:
    return {
        "group_id": "fdai-pantheon.Vidar",
        "agent_name": "Vidar",
        "topic": "object.action-run",
        "halt_revision": 1,
        "halt_record_digest": "sha256:" + "a" * 64,
        "parked_record_topic": "object.action-run.dlq",
        "parked_record_key": "resource-one",
        "parked_record_offset": 0,
        "parked_record_digest": "sha256:" + "b" * 64,
    }


@pytest.mark.asyncio
async def test_clear_acceptance_requires_owner_and_publishes_versioned_request() -> None:
    store = _Store()
    publisher = _Publisher()
    service = OrderedPoisonHaltClearService(
        store=store,
        publisher=publisher,
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
    )
    principal = OperatorPrincipal(
        subject_id="owner-one",
        roles=frozenset({OperatorRole.OWNER}),
        principal_kind=OperatorPrincipalKind.HUMAN,
    )

    receipt = await service.accept(
        principal=principal,
        idempotency_key="clear-key",
        body=_body(),
    )

    assert receipt.accepted is True
    assert publisher.published[0][0] == ORDERED_POISON_HALT_CLEAR_TOPIC
    assert publisher.published[0][1] == "clear-key"
    assert store.proposals[0][0] == "bus.ordered-poison-halt.clear"


@pytest.mark.asyncio
async def test_clear_acceptance_rejects_non_owner() -> None:
    service = OrderedPoisonHaltClearService(
        store=_Store(),
        publisher=_Publisher(),
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
    )
    principal = OperatorPrincipal(
        subject_id="reader-one",
        roles=frozenset({OperatorRole.READER}),
        principal_kind=OperatorPrincipalKind.HUMAN,
    )

    with pytest.raises(PermissionError):
        await service.accept(principal=principal, idempotency_key="clear-key", body=_body())


def _verify(token: str) -> Mapping[str, object]:
    role = {
        "owner": OperatorRole.OWNER,
        "contributor": OperatorRole.CONTRIBUTOR,
        "reader": OperatorRole.READER,
    }.get(token)
    return {
        "oid": f"{token}-id",
        "idtyp": "user",
        "roles": [role.value] if role is not None else [],
    }


def _route_client(
    *,
    store: _Store | None = None,
    publisher: _Publisher | None = None,
) -> tuple[TestClient, _Store, _Publisher]:
    resolved_store = store or _Store()
    resolved_publisher = publisher or _Publisher()
    authenticator = OperatorAuthenticator(verifier=_verify, group_ids={})
    authorizer = OperatorFamilyAuthorizer(authenticator)
    unavailable_conversation = UnavailableConversationAdapters()
    unavailable_workflow = UnavailableWorkflowAdapters()
    unavailable_operations = UnavailableOperationsAdapters()
    app = build_operator_app(
        authenticator=authenticator,
        read_model=object(),  # type: ignore[arg-type]
        data_sources=(),
        route_families=OperatorRouteFamilies(
            conversation=ConversationFamilyDependencies(
                authorizer=authorizer,
                projections=unavailable_conversation,
                outbox=unavailable_conversation,
                streams=unavailable_conversation,
            ),
            iam=build_unavailable_iam_bindings(authorizer=authorizer, role_group_ids={}),
            workflow_authorize=authorizer.workflow,
            workflow_read_store=unavailable_workflow,
            workflow_proposal_writer=unavailable_workflow,
            operations_projection_reader=unavailable_operations,
            operations_proposal_writer=unavailable_operations,
            operations_replay_reader=unavailable_operations,
            operations_webhook_verifier=unavailable_operations,
            poison_halt_clear=OrderedPoisonHaltClearService(
                store=resolved_store,
                publisher=resolved_publisher,
                clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
            ),
        ),
        readiness_probe=lambda: True,
        live_stream_hub=LiveStreamHub(),
        agent_stream_hub=LiveStreamHub(),
    )
    return TestClient(app), resolved_store, resolved_publisher


def test_route_accepts_owner_and_reports_queued_not_completed() -> None:
    client, store, publisher = _route_client()

    response = client.post(
        "/operations/bus/ordered-poison-halts/clear",
        json=_body(),
        headers={"Authorization": "Bearer owner", "Idempotency-Key": "clear-route"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["submitted"] is True
    assert body["completed"] is False
    assert body["dispatch_status"] == "queued"
    assert store.proposals[0][1] == "clear-route"
    assert publisher.published[0][0] == ORDERED_POISON_HALT_CLEAR_TOPIC


@pytest.mark.parametrize("token", ["contributor", "reader"])
def test_route_rejects_non_owner_roles(token: str) -> None:
    client, store, publisher = _route_client()

    response = client.post(
        "/operations/bus/ordered-poison-halts/clear",
        json=_body(),
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "clear-route"},
    )

    assert response.status_code == 403
    assert store.proposals == []
    assert publisher.published == []


@pytest.mark.parametrize(
    "body",
    [
        {"topic": "object.action-run"},
        {**_body(), "halt_revision": 0},
        {**_body(), "parked_record_topic": "object.verdict.dlq"},
    ],
)
def test_route_rejects_malformed_or_stale_request(body: Mapping[str, object]) -> None:
    client, store, publisher = _route_client()

    response = client.post(
        "/operations/bus/ordered-poison-halts/clear",
        json=dict(body),
        headers={"Authorization": "Bearer owner", "Idempotency-Key": "clear-route"},
    )

    assert response.status_code == 400
    assert store.proposals == []
    assert publisher.published == []


def test_route_accepts_idempotent_replay() -> None:
    client, store, publisher = _route_client()
    headers = {"Authorization": "Bearer owner", "Idempotency-Key": "clear-route"}

    first = client.post("/operations/bus/ordered-poison-halts/clear", json=_body(), headers=headers)
    second = client.post(
        "/operations/bus/ordered-poison-halts/clear",
        json=_body(),
        headers=headers,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert len(store.proposals) == 1
    assert len(publisher.published) == 1
