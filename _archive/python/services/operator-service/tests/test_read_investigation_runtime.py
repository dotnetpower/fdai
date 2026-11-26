"""Focused tests for durable read-investigation publication."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    ReadInvestigationProposalClaim,
)
from fdai_operator_service.read_investigation_runtime import ReadInvestigationOutboxDrainer
from fdai_service_contracts.read_investigation import read_investigation_task_id


def _claim(*, body: Mapping[str, object] | None = None) -> ReadInvestigationProposalClaim:
    request_body: dict[str, object] = {
        "prompt": "Inspect the resource",
        "intent": "resource_state",
        "resource_name": "service-one",
    }
    if body is not None:
        request_body.update(body)
    return ReadInvestigationProposalClaim(
        key="operator-proposal:operations:one",
        claim_id="claim-one",
        request_id="operator-request-one",
        principal_id="principal-one",
        idempotency_key="idempotency-one",
        correlation_id="correlation-one",
        payload={
            "operation": "read_investigation.start",
            "principal_id": "principal-one",
            "idempotency_key": "idempotency-one",
            "correlation_id": "correlation-one",
            "payload": request_body,
        },
        accepted_at="2026-08-23T00:00:00+00:00",
        attempt=1,
    )


def _cancel_claim(
    *,
    roles: tuple[str, ...] = ("Contributor",),
    task_id: str = "background-one",
) -> ReadInvestigationProposalClaim:
    return ReadInvestigationProposalClaim(
        key="operator-proposal:conversation:cancel-one",
        claim_id="claim-cancel",
        request_id="operator-cancel-one",
        principal_id="principal-one",
        idempotency_key="cancel-one",
        correlation_id=None,
        payload={
            "operation": "background.cancel",
            "scope": {"subject_id": "principal-one", "roles": list(roles)},
            "idempotency_key": "cancel-one",
            "path_params": {"task_id": task_id},
            "body": {},
            "query": {},
            "confirmed": False,
            "cancellation": True,
        },
        accepted_at="2026-08-23T00:00:00+00:00",
        attempt=1,
    )


class _Store:
    def __init__(self, claim: ReadInvestigationProposalClaim) -> None:
        self.claim = claim
        self.marked: list[tuple[str, str]] = []
        self.released: list[tuple[str, str]] = []
        self.rejected: list[tuple[str, str, str]] = []

    async def claim_read_investigation_proposal(
        self, **kwargs: object
    ) -> ReadInvestigationProposalClaim | None:
        assert kwargs == {"worker_id": "operator-read-investigation", "lease_seconds": 120}
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


async def test_store_claim_binds_proposal_prefix_as_data(
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

    claim = await store.claim_read_investigation_proposal(
        worker_id="operator-read-investigation",
        lease_seconds=120,
    )

    assert claim is not None
    assert "LIKE %(proposal_prefix)s" in statements[0]
    assert "operator-proposal:%" not in statements[0]
    assert "'claim_id', %(claim_id)s::text" in statements[0]
    assert "'claim_worker_id', %(worker_id)s::text" in statements[0]
    assert parameters_seen[0]["proposal_prefix"] == "operator-proposal:%"


async def test_drainer_publishes_versioned_no_authority_request_then_acknowledges() -> None:
    store = _Store(_claim(body={"prompt": "Inspect", "explicit_deep": True}))
    publisher = _Publisher()
    drainer = ReadInvestigationOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=publisher,
    )

    assert await drainer.run_once() is True

    topic, key, payload = publisher.published[0]
    assert (topic, key) == (
        "operator.read-investigation.requests",
        read_investigation_task_id("principal-one", "idempotency-one"),
    )
    assert payload["schema_version"] == "1.0.0"
    assert payload["owner_principal_id"] == "principal-one"
    assert payload["intent"] == "resource_state"
    assert payload["selector"] == {
        "name": "service-one",
        "resource_type": None,
        "resource_group": None,
    }
    assert payload["explicit_deep"] is True
    assert payload["execution_authority"] is False
    assert payload["capability_profile_id"] == "background.read-only"
    assert payload["origin"]["channel_kind"] == "web"  # type: ignore[index]
    assert store.marked == [("operator-proposal:operations:one", "claim-one")]
    assert store.released == []
    assert store.rejected == []


async def test_drainer_releases_transport_failure_for_retry() -> None:
    store = _Store(_claim())
    drainer = ReadInvestigationOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=_Publisher(fail=True),
    )

    assert await drainer.run_once() is False
    assert store.marked == []
    assert store.released == [("operator-proposal:operations:one", "claim-one")]


async def test_drainer_publishes_owner_scoped_cancellation() -> None:
    store = _Store(_cancel_claim(roles=("Owner",)))
    publisher = _Publisher()
    drainer = ReadInvestigationOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=publisher,
    )

    assert await drainer.run_once() is True
    topic, key, payload = publisher.published[0]
    assert (topic, key) == (
        "operator.read-investigation.requests",
        "background-one",
    )
    assert payload["command"] == "cancel"
    assert payload["task_id"] == "background-one"
    assert payload["owner_principal_id"] == "principal-one"
    assert payload["admin_override"] is True
    assert payload["execution_authority"] is False


async def test_start_and_cancel_share_one_task_lifecycle_partition() -> None:
    task_id = read_investigation_task_id("principal-one", "idempotency-one")
    publisher = _Publisher()

    await ReadInvestigationOutboxDrainer(
        store=_Store(_claim()),  # type: ignore[arg-type]
        publisher=publisher,
    ).run_once()
    await ReadInvestigationOutboxDrainer(
        store=_Store(_cancel_claim(task_id=task_id)),  # type: ignore[arg-type]
        publisher=publisher,
    ).run_once()

    assert [key for _topic, key, _payload in publisher.published] == [task_id, task_id]


async def test_drainer_rejects_unbounded_or_unknown_body_without_publish() -> None:
    for body in (
        {"prompt": "x" * 4_001},
        {"prompt": "Inspect", "budget": {"max_wall_seconds": 3_600}},
        {"prompt": "Inspect", "explicit_deep": "yes"},
        {"intent": "invented"},
        {"resource_name": ""},
    ):
        store = _Store(_claim(body=body))
        publisher = _Publisher()
        drainer = ReadInvestigationOutboxDrainer(
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
                "invalid_read_investigation_request",
            )
        ]
