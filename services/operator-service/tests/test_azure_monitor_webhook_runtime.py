"""Azure Monitor webhook durable publication tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

import pytest
from fdai_operator_service.azure_monitor_webhook_runtime import (
    AzureMonitorEventPublisher,
    AzureMonitorWebhookOutboxDrainer,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    WebhookProposalClaim,
)
from fdai_service_contracts.azure_monitor import normalize_common_alert_schema

_NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _event() -> dict[str, object]:
    events = normalize_common_alert_schema(
        {
            "schemaId": "azureMonitorCommonAlertSchema",
            "data": {
                "essentials": {
                    "alertId": "alert-instance-1",
                    "alertRule": "example-cpu-alert",
                    "severity": "Sev2",
                    "signalType": "Metric",
                    "monitorCondition": "Fired",
                    "monitoringService": "Platform",
                    "alertTargetIDs": [
                        "/subscriptions/00000000-0000-0000-0000-000000000001/"
                        "resourceGroups/rg/providers/Example/widgets/a"
                    ],
                    "firedDateTime": "2026-08-28T11:59:00+00:00",
                }
            },
        },
        ingested_at=_NOW,
    )
    return events[0].model_dump(mode="json")


@dataclass
class _Store:
    claim: WebhookProposalClaim | None
    published: list[tuple[str, str]] = field(default_factory=list)
    released: list[tuple[str, str]] = field(default_factory=list)
    rejected: list[tuple[str, str, str]] = field(default_factory=list)

    async def claim_webhook_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> WebhookProposalClaim | None:
        del worker_id, lease_seconds
        claim, self.claim = self.claim, None
        return claim

    async def mark_proposal_published(self, *, key: str, claim_id: str) -> bool:
        self.published.append((key, claim_id))
        return True

    async def release_proposal_claim(self, *, key: str, claim_id: str) -> bool:
        self.released.append((key, claim_id))
        return True

    async def mark_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool:
        self.rejected.append((key, claim_id, reason_code))
        return True


@dataclass
class _Publisher:
    fail: bool = False
    events: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)

    async def publish(
        self,
        topic: str,
        key: str,
        payload: dict[str, object],
    ) -> object:
        if self.fail:
            raise RuntimeError("broker unavailable")
        self.events.append((topic, key, payload))
        return object()


def _claim(payload: dict[str, object]) -> WebhookProposalClaim:
    return WebhookProposalClaim(
        key="operator-proposal:operations:alert-1",
        claim_id="claim-1",
        payload=payload,
        attempt=1,
    )


async def test_drainer_publishes_normalized_event_and_closes_claim() -> None:
    store = _Store(_claim({"schema_version": "1.0.0", "events": [_event()]}))
    publisher = _Publisher()
    drainer = AzureMonitorWebhookOutboxDrainer(
        store=cast(PostgresFamilyStore, store),
        publisher=cast(AzureMonitorEventPublisher, publisher),
        topic="fdai.events",
    )

    assert await drainer.run_once() is True
    assert store.published == [("operator-proposal:operations:alert-1", "claim-1")]
    assert store.released == []
    assert publisher.events[0][0] == "fdai.events"
    assert publisher.events[0][1] == publisher.events[0][2]["resource_ref"]


async def test_drainer_releases_claim_after_transport_failure() -> None:
    store = _Store(_claim({"schema_version": "1.0.0", "events": [_event()]}))
    drainer = AzureMonitorWebhookOutboxDrainer(
        store=cast(PostgresFamilyStore, store),
        publisher=cast(AzureMonitorEventPublisher, _Publisher(fail=True)),
        topic="fdai.events",
    )

    assert await drainer.run_once() is False
    assert store.released == [("operator-proposal:operations:alert-1", "claim-1")]
    assert store.rejected == []


async def test_drainer_rejects_malformed_durable_event() -> None:
    store = _Store(_claim({"schema_version": "1.0.0", "events": [{"mode": "enforce"}]}))
    drainer = AzureMonitorWebhookOutboxDrainer(
        store=cast(PostgresFamilyStore, store),
        publisher=cast(AzureMonitorEventPublisher, _Publisher()),
        topic="fdai.events",
    )

    assert await drainer.run_once() is False
    assert store.rejected == [
        (
            "operator-proposal:operations:alert-1",
            "claim-1",
            "invalid_azure_monitor_event",
        )
    ]


async def test_store_claim_filters_only_azure_monitor_webhooks(
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
        return [
            {
                "key": "operator-proposal:operations:alert-1",
                "value": {
                    "payload": {"schema_version": "1.0.0", "events": [_event()]},
                    "attempt": 1,
                },
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    claim = await store.claim_webhook_proposal(worker_id="worker-one", lease_seconds=30)

    assert claim is not None
    assert "value ->> 'family' = 'operations'" in statements[0]
    assert "value ->> 'operation' = 'webhook.azure_monitor'" in statements[0]
    assert "FOR UPDATE SKIP LOCKED" in statements[0]
