from __future__ import annotations

import asyncio
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
from fdai_operator_service.operator_request_receipt import OperatorRequestReceiptIssuer
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
    record: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _Claim:
    key: str
    claim_id: str
    payload: Mapping[str, object]
    attempt: int


class _Store:
    def __init__(self, *, fail_mark: bool = False) -> None:
        self.proposals: list[tuple[str, str, Mapping[str, object]]] = []
        self.records: dict[str, dict[str, object]] = {}
        self.released: list[str] = []
        self.fail_mark = fail_mark
        self._lock = asyncio.Lock()

    async def append_proposal(self, **kwargs: object) -> object:
        async with self._lock:
            key = f"operator-proposal:operations:{kwargs['idempotency_key']}"
            existing = self.records.get(key)
            if existing is not None:
                return _Stored(duplicate=True, record=dict(existing))
            record = {
                "family": kwargs["family"],
                "operation": kwargs["operation"],
                "idempotency_key": kwargs["idempotency_key"],
                "dispatch_status": "pending",
                "payload": kwargs["payload"],
            }
            self.records[key] = record
            self.proposals.append(
                (
                    str(kwargs["operation"]),
                    str(kwargs["idempotency_key"]),
                    kwargs["payload"],  # type: ignore[arg-type]
                )
            )
            return _Stored(duplicate=False, record=dict(record))

    async def claim_poison_halt_clear_proposal(
        self,
        *,
        idempotency_key: str,
        worker_id: str,
        lease_seconds: int,
    ) -> object | None:
        del worker_id, lease_seconds
        async with self._lock:
            key = f"operator-proposal:operations:{idempotency_key}"
            record = self.records.get(key)
            if record is None or record["dispatch_status"] != "pending":
                return None
            attempt = int(record.get("attempt", 0)) + 1
            record.update(
                {
                    "dispatch_status": "claimed",
                    "claim_id": f"claim-{attempt}",
                    "attempt": attempt,
                }
            )
            return _Claim(
                key=key,
                claim_id=str(record["claim_id"]),
                payload=record["payload"],  # type: ignore[arg-type]
                attempt=attempt,
            )

    @property
    def published(self) -> set[str]:
        if not hasattr(self, "_published"):
            self._published: set[str] = set()
        return self._published

    async def mark_poison_halt_clear_claim_published(self, *, key: str, claim_id: str) -> bool:
        if self.fail_mark:
            return False
        async with self._lock:
            record = self.records.get(key)
            if (
                record is None
                or record.get("dispatch_status") != "claimed"
                or record.get("claim_id") != claim_id
            ):
                return False
            record["dispatch_status"] = "published"
            self.published.add(str(record["idempotency_key"]))
            return True

    async def release_poison_halt_clear_claim(self, *, key: str, claim_id: str) -> bool:
        async with self._lock:
            record = self.records.get(key)
            if (
                record is None
                or record.get("dispatch_status") != "claimed"
                or record.get("claim_id") != claim_id
            ):
                return False
            record["dispatch_status"] = "pending"
            record.pop("claim_id", None)
            self.released.append(key)
            return True


class _Publisher:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.published: list[tuple[str, str, Mapping[str, object]]] = []
        self.fail_first = fail_first

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("broker unavailable")
        self.published.append((topic, key, payload))
        return object()


class _BlockingPublisher(_Publisher):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        self.entered.set()
        await self.release.wait()
        return await super().publish(topic, key, payload)


class _Signer:
    def sign_operator_request_receipt(self, signing_bytes: bytes) -> bytes:
        return b"signed:" + signing_bytes[:16]


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
        receipt_issuer=OperatorRequestReceiptIssuer(
            signer=_Signer(),
            producer_service_identity="operator-service",
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        ),
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
    assert "clear-key" in store.published


@pytest.mark.asyncio
async def test_clear_acceptance_refuses_unavailable_receipt_issuer() -> None:
    service = OrderedPoisonHaltClearService(
        store=_Store(),
        publisher=_Publisher(),
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
    )
    principal = OperatorPrincipal(
        subject_id="owner-one",
        roles=frozenset({OperatorRole.OWNER}),
        principal_kind=OperatorPrincipalKind.HUMAN,
    )

    with pytest.raises(RuntimeError, match="receipt issuer is unavailable"):
        await service.accept(principal=principal, idempotency_key="clear-key", body=_body())


@pytest.mark.asyncio
async def test_clear_acceptance_attaches_signed_exact_request_receipt() -> None:
    store = _Store()
    publisher = _Publisher()
    service = OrderedPoisonHaltClearService(
        store=store,
        publisher=publisher,
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        receipt_issuer=OperatorRequestReceiptIssuer(
            signer=_Signer(),
            producer_service_identity="operator-service",
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )
    principal = OperatorPrincipal(
        subject_id="owner-one",
        roles=frozenset({OperatorRole.OWNER}),
        principal_kind=OperatorPrincipalKind.HUMAN,
    )

    await service.accept(
        principal=principal,
        idempotency_key="clear-key",
        body=_body(),
    )

    payload = publisher.published[0][2]
    receipt = payload["operator_request_receipt"]
    assert isinstance(receipt, Mapping)
    assert receipt["producer_service_identity"] == "operator-service"
    assert receipt["initiator_principal"] == "owner-one"
    assert receipt["action_type"] == "bus.ordered-poison-halt.clear"


@pytest.mark.asyncio
async def test_clear_acceptance_rejects_non_owner() -> None:
    service = OrderedPoisonHaltClearService(
        store=_Store(),
        publisher=_Publisher(),
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        receipt_issuer=OperatorRequestReceiptIssuer(
            signer=_Signer(),
            producer_service_identity="operator-service",
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        ),
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
                receipt_issuer=OperatorRequestReceiptIssuer(
                    signer=_Signer(),
                    producer_service_identity="operator-service",
                    clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
                ),
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


def test_route_returns_unavailable_when_receipt_issuer_is_missing() -> None:
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
            poison_halt_clear=None,
        ),
        readiness_probe=lambda: True,
        live_stream_hub=LiveStreamHub(),
        agent_stream_hub=LiveStreamHub(),
    )
    client = TestClient(app)

    response = client.post(
        "/operations/bus/ordered-poison-halts/clear",
        json=_body(),
        headers={"Authorization": "******", "Idempotency-Key": "clear-route"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "ordered poison halt clear is not configured"


@pytest.mark.asyncio
async def test_clear_retry_republishes_when_first_publish_fails_before_send() -> None:
    store = _Store()
    publisher = _Publisher(fail_first=True)
    service = OrderedPoisonHaltClearService(
        store=store,
        publisher=publisher,
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        receipt_issuer=OperatorRequestReceiptIssuer(
            signer=_Signer(),
            producer_service_identity="operator-service",
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )
    principal = OperatorPrincipal(
        subject_id="owner-one",
        roles=frozenset({OperatorRole.OWNER}),
        principal_kind=OperatorPrincipalKind.HUMAN,
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await service.accept(principal=principal, idempotency_key="clear-key", body=_body())
    receipt = await service.accept(principal=principal, idempotency_key="clear-key", body=_body())

    assert receipt.accepted is True
    assert len(store.proposals) == 1
    assert len(publisher.published) == 1
    assert publisher.published[0][1] == "clear-key"
    assert "clear-key" in store.published


@pytest.mark.asyncio
async def test_clear_concurrent_accept_claims_once_before_publishing() -> None:
    store = _Store()
    publisher = _BlockingPublisher()
    service = OrderedPoisonHaltClearService(
        store=store,
        publisher=publisher,
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        receipt_issuer=OperatorRequestReceiptIssuer(
            signer=_Signer(),
            producer_service_identity="operator-service",
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )
    principal = OperatorPrincipal(
        subject_id="owner-one",
        roles=frozenset({OperatorRole.OWNER}),
        principal_kind=OperatorPrincipalKind.HUMAN,
    )

    first = asyncio.create_task(
        service.accept(principal=principal, idempotency_key="clear-key", body=_body())
    )
    await publisher.entered.wait()
    second = await service.accept(principal=principal, idempotency_key="clear-key", body=_body())
    publisher.release.set()
    first_result = await first

    assert first_result.accepted is True
    assert second.accepted is True
    assert len(store.proposals) == 1
    assert len(publisher.published) == 1


@pytest.mark.asyncio
async def test_clear_retry_after_mark_failure_does_not_republish_live_claim() -> None:
    store = _Store(fail_mark=True)
    publisher = _Publisher()
    service = OrderedPoisonHaltClearService(
        store=store,
        publisher=publisher,
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        receipt_issuer=OperatorRequestReceiptIssuer(
            signer=_Signer(),
            producer_service_identity="operator-service",
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )
    principal = OperatorPrincipal(
        subject_id="owner-one",
        roles=frozenset({OperatorRole.OWNER}),
        principal_kind=OperatorPrincipalKind.HUMAN,
    )

    with pytest.raises(RuntimeError, match="publication state was not recorded"):
        await service.accept(principal=principal, idempotency_key="clear-key", body=_body())
    replay = await service.accept(principal=principal, idempotency_key="clear-key", body=_body())

    assert replay.accepted is True
    assert len(publisher.published) == 1
