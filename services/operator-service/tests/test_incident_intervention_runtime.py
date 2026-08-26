"""Focused tests for durable Incident intervention publication."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai_operator_service.incident_intervention_runtime import (
    IncidentInterventionOutboxDrainer,
)
from fdai_operator_service.postgres_family_store import (
    IncidentInterventionProposalClaim,
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)

INCIDENT_ID = "00000000-0000-0000-0000-000000000123"
TARGET_REF = "sha256:" + "a" * 64


def _claim(*, body: Mapping[str, object] | None = None) -> IncidentInterventionProposalClaim:
    request_body: dict[str, object] = {
        "action": "operator_guidance",
        "incident_id": INCIDENT_ID,
        "correlation_id": "correlation-one",
        "expected_state": "triaging",
        "comment": "Preserve this operator context.",
        "target_ref": TARGET_REF,
        "principal_roles": ["Contributor"],
    }
    if body is not None:
        request_body.update(body)
    return IncidentInterventionProposalClaim(
        key="operator-proposal:operations:one",
        claim_id="claim-one",
        request_id="operator-request-one",
        principal_id="principal-one",
        idempotency_key="idempotency-one",
        correlation_id="correlation-one",
        payload={
            "operation": "incident.intervention",
            "principal_id": "principal-one",
            "idempotency_key": "idempotency-one",
            "correlation_id": "correlation-one",
            "payload": request_body,
        },
        accepted_at="2026-08-24T00:00:00+00:00",
        attempt=1,
    )


class _Store:
    def __init__(self, claim: IncidentInterventionProposalClaim) -> None:
        self.claim = claim
        self.marked: list[tuple[str, str]] = []
        self.released: list[tuple[str, str]] = []
        self.rejected: list[tuple[str, str, str]] = []

    async def claim_incident_intervention_proposal(
        self, **kwargs: object
    ) -> IncidentInterventionProposalClaim | None:
        assert kwargs == {"worker_id": "operator-incident-intervention", "lease_seconds": 120}
        claim, self.claim = self.claim, None  # type: ignore[assignment]
        return claim

    async def mark_proposal_published(self, *, key: str, claim_id: str) -> bool:
        self.marked.append((key, claim_id))
        return True

    async def release_proposal_claim(self, *, key: str, claim_id: str) -> bool:
        self.released.append((key, claim_id))
        return True

    async def mark_proposal_rejected(self, *, key: str, claim_id: str, reason_code: str) -> bool:
        self.rejected.append((key, claim_id, reason_code))
        return True


class _Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, Mapping[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.published.append((topic, key, payload))
        return object()


async def test_store_claim_is_operation_specific_and_binds_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    parameters_seen: list[Mapping[str, object]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        statements.append(statement)
        parameters_seen.append(parameters)
        claim = _claim()
        return [
            {
                "key": claim.key,
                "value": {
                    "proposal_id": claim.request_id,
                    "principal_id": claim.principal_id,
                    "idempotency_key": claim.idempotency_key,
                    "accepted_at": claim.accepted_at,
                    "payload": claim.payload,
                    "attempt": claim.attempt,
                },
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    claim = await store.claim_incident_intervention_proposal(
        worker_id="operator-incident-intervention",
        lease_seconds=120,
    )

    assert claim is not None
    assert "value ->> 'operation' = 'incident.intervention'" in statements[0]
    assert "LIKE %(proposal_prefix)s" in statements[0]
    assert "operator-proposal:%" not in statements[0]
    assert parameters_seen[0]["proposal_prefix"] == "operator-proposal:%"


async def test_drainer_publishes_versioned_no_authority_request_then_acknowledges() -> None:
    store = _Store(_claim())
    publisher = _Publisher()
    drainer = IncidentInterventionOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=publisher,
    )

    assert await drainer.run_once() is True

    topic, key, payload = publisher.published[0]
    assert (topic, key) == ("operator.incident-intervention.requests", INCIDENT_ID)
    assert payload["schema_version"] == "1.0.0"
    assert payload["target_ref"] == TARGET_REF
    assert isinstance(payload["request_digest"], str)
    assert payload["request_digest"].startswith("sha256:")
    assert payload["accountable_agent"] == "Saga"
    assert payload["execution_authority"] is False
    assert store.marked == [("operator-proposal:operations:one", "claim-one")]
    assert store.released == []
    assert store.rejected == []


async def test_drainer_releases_transport_failure_for_retry() -> None:
    store = _Store(_claim())
    drainer = IncidentInterventionOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=_Publisher(fail=True),
    )

    assert await drainer.run_once() is False
    assert store.marked == []
    assert store.released == [("operator-proposal:operations:one", "claim-one")]


async def test_drainer_rejects_tampered_or_invalid_request_without_publish() -> None:
    claims = (
        _claim(body={"target_ref": "raw-resource-id"}),
        _claim(body={"principal_roles": ["Reader"]}),
        _claim(body={"comment": ""}),
        _claim(body={"unexpected": True}),
        _claim(body={"correlation_id": "different-correlation"}),
    )
    for claim in claims:
        store = _Store(claim)
        publisher = _Publisher()
        drainer = IncidentInterventionOutboxDrainer(
            store=store,  # type: ignore[arg-type]
            publisher=publisher,
        )

        assert await drainer.run_once() is False
        assert publisher.published == []
        assert store.released == []
        assert store.rejected == [
            (
                "operator-proposal:operations:one",
                "claim-one",
                "invalid_incident_intervention_request",
            )
        ]
