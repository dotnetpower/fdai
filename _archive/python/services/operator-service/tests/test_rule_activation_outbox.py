from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_operator_service.postgres_rule_activation_outbox import PostgresRuleActivationOutbox
from fdai_operator_service.rule_activation_notice import rule_activation_notice_from_record
from fdai_operator_service.rule_activation_outbox import (
    RuleActivationNoticeDrainer,
    RuleActivationProposalClaim,
)
from fdai_service_contracts.rule_activation_transport import RULE_ACTIVATION_REQUEST_TOPIC


def _record() -> tuple[str, dict[str, object]]:
    idempotency_key = "disable-rule-beta"
    request = {
        "family": "workflow",
        "operation": "rule.activation-request",
        "principal_id": "requester",
        "idempotency_key": idempotency_key,
        "payload": {
            "operation": "rule.activation-request",
            "principal_id": "requester",
            "principal_roles": ["Contributor"],
            "idempotency_key": idempotency_key,
            "expected_revision": "a" * 64,
            "path_parameters": {},
            "payload": {
                "mode": "shadow",
                "reason": "Disable a reviewed Rule.",
                "changes": [{"rule_id": "rule.beta", "enabled": False}],
            },
            "mode": "shadow",
            "request_source": "operator-http:test",
        },
    }
    digest = hashlib.sha256(
        json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    key = "operator-proposal:workflow:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
    return key, {
        "kind": "operator.proposal",
        "proposal_id": f"operator-{digest[:32]}",
        "request_digest": digest,
        "dispatch_status": "pending",
        "mode": "shadow",
        "accepted_at": datetime(2026, 9, 22, tzinfo=UTC).isoformat(),
        **request,
    }


class Store:
    def __init__(self, claim: RuleActivationProposalClaim) -> None:
        self._claim = claim
        self.finished: list[bool] = []
        self.released = False

    async def claim(self) -> RuleActivationProposalClaim | None:
        return self._claim

    async def finish(
        self,
        claim: RuleActivationProposalClaim,
        *,
        rejected: bool = False,
    ) -> bool:
        assert claim is self._claim
        self.finished.append(rejected)
        return True

    async def release(self, claim: RuleActivationProposalClaim) -> None:
        assert claim is self._claim
        self.released = True


class Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, Mapping[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        if self.fail:
            raise RuntimeError("transport unavailable")
        self.published.append((topic, key, payload))
        return object()


async def test_drainer_publishes_only_the_immutable_reference() -> None:
    key, record = _record()
    claim = RuleActivationProposalClaim(key, "claim-1", record)
    store = Store(claim)
    publisher = Publisher()

    assert await RuleActivationNoticeDrainer(store, publisher).run_once() is True

    topic, partition_key, payload = publisher.published[0]
    assert topic == RULE_ACTIVATION_REQUEST_TOPIC
    assert partition_key == record["proposal_id"]
    assert "payload" not in payload
    assert "principal_id" not in payload
    assert store.finished == [False]


async def test_drainer_releases_claim_when_transport_fails() -> None:
    key, record = _record()
    claim = RuleActivationProposalClaim(key, "claim-1", record)
    store = Store(claim)

    assert await RuleActivationNoticeDrainer(store, Publisher(fail=True)).run_once() is False
    assert store.released is True
    assert store.finished == []


def test_notice_rejects_tampered_request_content() -> None:
    key, record = _record()
    record["principal_id"] = "attacker"

    try:
        rule_activation_notice_from_record(key, record)
    except ValueError as exc:
        assert "durable identity" in str(exc)
    else:
        raise AssertionError("tampered proposal was accepted")


async def test_postgres_claim_requires_request_publication_before_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, record = _record()
    calls: list[str] = []

    async def query(
        _self: PostgresRuleActivationOutbox,
        sql: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        calls.append(sql)
        return [{"key": key, "value": record}]

    monkeypatch.setattr(PostgresRuleActivationOutbox, "_query", query)
    outbox = PostgresRuleActivationOutbox(
        PostgresFamilyStoreConfig(dsn="postgresql://localhost/example")
    )

    assert await outbox.claim() is not None
    assert "source_request.value ->> 'dispatch_status' = 'published'" in calls[0]
    assert "FOR UPDATE SKIP LOCKED" in calls[0]
