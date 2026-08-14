"""Focused tests for durable action-confirmation publication."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai_operator_service.action_confirmation_runtime import (
    ActionConfirmationOutboxDrainer,
)
from fdai_operator_service.postgres_family_store import (
    ActionProposalClaim,
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_service_contracts import query_content_digest
from fdai_service_contracts.action_intent import ActionIntentSource, OntologyActionIntent


def _intent(*, actor_ref: str = "operator:operator-one") -> dict[str, object]:
    arguments = {"replicas": 3, "target_resource_ref": "resource:service/api"}
    target = {"resource_ref": "resource:service/api"}
    material = {
        "schema_version": "1.0.0",
        "source": "operator_language",
        "actor_ref": actor_ref,
        "purpose": "operations-review",
        "ontology_release_digest": "sha256:" + "a" * 64,
        "action_type_name": "ops.scale-out",
        "action_type_version": "1.0.0",
        "action_declaration_digest": "sha256:" + "b" * 64,
        "arguments": arguments,
        "target_selector": target,
        "evidence_refs": ("semantic-frame:one",),
        "input_digest": "sha256:" + "c" * 64,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    return OntologyActionIntent(
        source=ActionIntentSource.OPERATOR_LANGUAGE,
        actor_ref=actor_ref,
        purpose="operations-review",
        ontology_release_digest="sha256:" + "a" * 64,
        action_type_name="ops.scale-out",
        action_type_version="1.0.0",
        action_declaration_digest="sha256:" + "b" * 64,
        arguments_json='{"replicas":3,"target_resource_ref":"resource:service/api"}',
        target_selector_json='{"resource_ref":"resource:service/api"}',
        evidence_refs=("semantic-frame:one",),
        input_digest="sha256:" + "c" * 64,
        intent_digest=query_content_digest(material),
    ).model_dump(mode="json")


def _claim(*, actor_ref: str = "operator:operator-one") -> ActionProposalClaim:
    return ActionProposalClaim(
        key="operator:proposal:conversation:one",
        claim_id="claim-one",
        principal_id="operator-one",
        payload={
            "idempotency_key": "action-one",
            "body": {
                "action_type": "ops.scale-out",
                "arguments": {
                    "replicas": 3,
                    "target_resource_ref": "resource:service/api",
                },
                "session_id": "session-one",
                "idempotency_key": "action-one",
                "request_id": "semantic-request-one",
                "projection_id": "semantic-projection-one",
                "ontology_intent": _intent(actor_ref=actor_ref),
            },
        },
        attempt=1,
    )


class _Store:
    def __init__(self, claim: ActionProposalClaim) -> None:
        self.claim = claim
        self.source_claim = claim
        self.marked: list[tuple[str, str]] = []
        self.released: list[tuple[str, str]] = []
        self.rejected: list[tuple[str, str, str]] = []

    async def read_semantic_action_draft_source(
        self,
        *,
        principal_id: str,
        request_id: str,
        projection_id: str,
    ) -> dict[str, object] | None:
        body = self.source_claim.payload["body"]
        assert isinstance(body, dict)
        assert principal_id == "operator-one"
        return {
            "request_id": request_id,
            "projection_id": projection_id,
            "idempotency_key": self.source_claim.payload["idempotency_key"],
            "status": "action_draft",
            "semantic_result": {
                "disposition": "action_draft",
                "session_id": body["session_id"],
                "action_intent": body["ontology_intent"],
            },
        }

    async def claim_action_proposal(self, **kwargs: object) -> ActionProposalClaim | None:
        assert kwargs == {"worker_id": "operator-action-confirmation", "lease_seconds": 120}
        claim, self.claim = self.claim, None  # type: ignore[assignment]
        return claim

    async def mark_action_proposal_published(self, *, key: str, claim_id: str) -> bool:
        self.marked.append((key, claim_id))
        return True

    async def release_action_proposal_claim(self, *, key: str, claim_id: str) -> bool:
        self.released.append((key, claim_id))
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


class _Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, Mapping[str, object]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.published.append((topic, key, payload))
        return object()


async def test_drainer_publishes_flat_operator_request_then_acknowledges() -> None:
    store = _Store(_claim())
    publisher = _Publisher()
    drainer = ActionConfirmationOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=publisher,
        topic="object.event",
    )

    assert await drainer.run_once() is True

    topic, key, event = publisher.published[0]
    assert (topic, key) == ("object.event", "action-one")
    assert event["event_type"] == "operator_request"
    assert event["initiator_principal"] == "operator-one"
    assert event["resource_id"] == "resource:service/api"
    assert event["ontology_intent"] == _intent()
    assert store.marked == [("operator:proposal:conversation:one", "claim-one")]
    assert store.released == []
    assert store.rejected == []


async def test_drainer_releases_transport_failure_for_retry() -> None:
    store = _Store(_claim())
    drainer = ActionConfirmationOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=_Publisher(fail=True),
        topic="object.event",
    )

    assert await drainer.run_once() is False
    assert store.marked == []
    assert store.released == [("operator:proposal:conversation:one", "claim-one")]


async def test_drainer_rejects_principal_mismatch_without_publish() -> None:
    store = _Store(_claim(actor_ref="operator:different"))
    publisher = _Publisher()
    drainer = ActionConfirmationOutboxDrainer(
        store=store,  # type: ignore[arg-type]
        publisher=publisher,
        topic="object.event",
    )

    assert await drainer.run_once() is False
    assert publisher.published == []
    assert store.released == []
    assert store.rejected == [
        (
            "operator:proposal:conversation:one",
            "claim-one",
            "invalid_semantic_action_source",
        )
    ]


async def test_store_claim_uses_generic_proposal_dispatch_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        statements.append(statement)
        return [
            {
                "key": "operator:proposal:conversation:one",
                "value": {
                    "principal_id": "operator-one",
                    "payload": _claim().payload,
                    "attempt": 1,
                },
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    claim = await store.claim_action_proposal(worker_id="worker-one", lease_seconds=30)

    assert claim is not None
    assert "value ->> 'family' = 'conversation'" in statements[0]
    assert "value ->> 'operation' = 'chat.action.confirm'" in statements[0]
    assert "value ->> 'dispatch_status' = 'pending'" in statements[0]
    assert "value ->> 'dispatch_status' = 'claimed'" in statements[0]
    assert "NOW() + make_interval(secs => %(lease_seconds)s)" in statements[0]
    assert "ORDER BY COALESCE((value ->> 'attempt')::integer, 0)" in statements[0]
    assert "value ->> 'accepted_at'" in statements[0]
    assert "value ->> 'state'" not in statements[0]


async def test_store_ack_requires_active_dispatch_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        return [{"value": {}}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert await store.mark_action_proposal_published(key="proposal-one", claim_id="claim-one")
    assert "'dispatch_status', %(state)s::text" in statements[0]
    assert "value ->> 'dispatch_status' = 'claimed'" in statements[0]


async def test_store_reject_closes_only_the_active_claim(
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
        return [{"value": {}}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert await store.mark_action_proposal_rejected(
        key="proposal-one",
        claim_id="claim-one",
        reason_code="invalid_semantic_action_source",
    )
    assert "'dispatch_status', 'rejected'" in statements[0]
    assert "value ->> 'dispatch_status' = 'claimed'" in statements[0]
    assert parameters_seen == [
        {
            "reason_code": "invalid_semantic_action_source",
            "key": "proposal-one",
            "claim_id": "claim-one",
        }
    ]


async def test_store_source_lookup_requires_principal_owned_request(
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
        return [{"data": {"status": "action_draft"}}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    source = await store.read_semantic_action_draft_source(
        principal_id="operator-one",
        request_id="request-one",
        projection_id="projection-one",
    )

    assert source == {"status": "action_draft"}
    assert "result.value -> 'data' AS data" in statements[0]
    assert "request.value ->> 'principal_id' = %(principal_id)s" in statements[0]
    assert "result.value ->> 'principal_id' = %(principal_id)s" in statements[0]
    assert "result.value ->> 'request_id' = %(request_id)s" in statements[0]
    assert "result.value ->> 'projection_id' = %(projection_id)s" in statements[0]
    assert "result.value #>> '{data,status}' = 'action_draft'" in statements[0]
    assert parameters_seen == [
        {
            "principal_id": "operator-one",
            "request_id": "request-one",
            "projection_id": "projection-one",
        }
    ]
