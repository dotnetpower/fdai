"""Guarded task delivery never substitutes broker state for execution authority."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.kubernetes_connector_tasks import (
    ConnectorTaskDeliveryError,
    ConnectorTaskDeliveryQueue,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai_service_contracts.cluster_connector import ConnectorRegistration, ConnectorWork

NOW = datetime(2026, 10, 4, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


class Registrations:
    def __init__(self) -> None:
        self.registration = registration()

    async def read(self, principal_ref: str) -> ConnectorRegistration | None:
        return self.registration if principal_ref == self.registration.principal_ref else None


def registration() -> ConnectorRegistration:
    return ConnectorRegistration.model_validate(
        {
            "scope": {
                "deployment_ref": "example",
                "cluster_ref": "cluster-example",
                "connector_id": "executor",
                "enrollment_revision": 1,
            },
            "principal_ref": "executor-principal",
            "role": "executor",
            "namespaces": ["example"],
            "capabilities": ["governed.execute"],
            "valid_from": NOW - timedelta(minutes=1),
            "expires_at": NOW + timedelta(minutes=10),
        }
    )


def work(**changes: object) -> ConnectorWork:
    value = {
        "scope": registration().scope.model_dump(mode="json"),
        "work_id": "work-example",
        "correlation_id": "correlation-example",
        "capability": "governed.execute",
        "namespace": "example",
        "target_uid": "pod-example",
        "target_revision": "42",
        "artifact_digest": DIGEST,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "idempotency_key": "idempotency-example",
    }
    value.update(changes)
    return ConnectorWork.model_validate(value)


async def test_current_authorization_duplicate_suppression_and_acknowledgement() -> None:
    store, registrations = InMemoryStateStore(), Registrations()
    queue = ConnectorTaskDeliveryQueue(store, registrations=registrations, now=lambda: NOW)
    first = await queue.deliver(work(), principal_ref="executor-principal")
    assert first.status == "delivered"
    assert first.execution_authority is False
    duplicate = await queue.deliver(work(), principal_ref="executor-principal")
    assert duplicate.status == "duplicate"
    assert duplicate.claim_fence == first.claim_fence
    assert len(list(store.audit_entries)) == 1
    assert await queue.acknowledge(
        work(),
        principal_ref="executor-principal",
        claim_fence=first.claim_fence,
        outcome_digest=DIGEST,
    )
    assert (await queue.deliver(work(), principal_ref="executor-principal")).status == "duplicate"
    assert [entry["entry"]["kind"] for entry in store.audit_entries] == [
        "kubernetes.connector.work.delivered",
        "kubernetes.connector.work.acknowledged",
    ]


async def test_revoked_registration_and_wrong_principal_do_not_deliver() -> None:
    store, registrations = InMemoryStateStore(), Registrations()
    queue = ConnectorTaskDeliveryQueue(store, registrations=registrations, now=lambda: NOW)
    with pytest.raises(ConnectorTaskDeliveryError):
        await queue.deliver(work(), principal_ref="foreign-principal")
    registrations.registration = registration().model_copy(update={"revoked": True})
    with pytest.raises(ValueError, match="registration"):
        await queue.deliver(work(), principal_ref="executor-principal")
    assert list(store.audit_entries) == []


async def test_expired_claim_records_unknown_outcome_before_redelivery(tmp_path) -> None:
    clock = [NOW]
    store, registrations = InMemoryStateStore(), Registrations()
    queue = ConnectorTaskDeliveryQueue(
        store, registrations=registrations, now=lambda: clock[0], claim_seconds=1
    )
    first = await queue.deliver(work(), principal_ref="executor-principal")
    clock[0] += timedelta(seconds=1)
    recovered = await queue.deliver(work(), principal_ref="executor-principal")
    assert recovered.status == "unknown_outcome"
    assert recovered.claim_fence == first.claim_fence
    with pytest.raises(ConnectorTaskDeliveryError, match="not current"):
        await queue.acknowledge(
            work(),
            principal_ref="executor-principal",
            claim_fence=first.claim_fence,
            outcome_digest=DIGEST,
        )
    assert [entry["entry"]["kind"] for entry in store.audit_entries] == [
        "kubernetes.connector.work.delivered",
        "kubernetes.connector.work.unknown_outcome",
    ]
