"""Cost Governance notification activation and disclosure tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fdai.shared.providers.cost_governance import CostPackageActivation
from fdai.shared.providers.notifications import NotificationMessage
from fdai_service_contracts import (
    DISCLOSURE_PRESETS,
    CostAmountPrecision,
    CostDisclosurePolicy,
    CostGranularity,
    CostIdentityVisibility,
    CostProjectionRecord,
)

from fdai_cost_governance.notifications import CostGovernanceNotificationProducer

NOW = datetime(2026, 8, 28, tzinfo=UTC)


class Dependencies:
    """Record package-gate reads and dispatches."""

    def __init__(self) -> None:
        self.available = True
        self.enabled = True
        self.policy = DISCLOSURE_PRESETS["masked"]
        self.calls: list[str] = []
        self.messages: list[NotificationMessage] = []

    async def read_cost_activation(self, package_id: str) -> CostPackageActivation:
        self.calls.append("activation")
        return CostPackageActivation(
            vertical_id="cost-governance",
            package_id=package_id,
            available=self.available,
            enabled=self.enabled and self.available,
            availability_reasons=(() if self.available else ("missing_provider:cost-estimator",)),
            package_version="0.1.0",
            image_digest=f"sha256:{'b' * 64}",
            asset_manifest_digest=f"sha256:{'c' * 64}",
            semantic_profile_digest=f"sha256:{'d' * 64}",
            revision=3,
            effective_at=NOW,
            ontology_release_id="fdai-operational-vocabulary-v1",
            ontology_release_digest=f"sha256:{'a' * 64}",
            source_authority="vertical-package-manager",
        )

    async def read_notification_disclosure(self, destination_scope: str, *, now: datetime):
        assert destination_scope == "governance"
        assert now == NOW
        self.calls.append("disclosure")
        return self.policy

    async def dispatch(self, message: NotificationMessage) -> object:
        self.calls.append("dispatch")
        self.messages.append(message)
        return object()


def _record() -> CostProjectionRecord:
    return CostProjectionRecord(
        record_id="costobs:1",
        group_id="compute",
        resource_id="private-resource",
        service_id="compute",
        amount=Decimal("120"),
        previous_amount=Decimal("100"),
        currency="USD",
        observed_at=NOW,
        completeness=Decimal("1"),
        source_authority="azure-cost-management",
        provenance_digest=f"sha256:{'a' * 64}",
    )


@pytest.mark.asyncio
async def test_disabled_package_produces_zero_notification_sends() -> None:
    dependencies = Dependencies()
    dependencies.enabled = False
    producer = CostGovernanceNotificationProducer(
        activation=dependencies,
        disclosure=dependencies,
        dispatcher=dependencies,
        pseudonym_key=bytes(range(32)),
    )
    assert not await producer.dispatch(
        destination_scope="governance",
        correlation_id="cost-1",
        records=(_record(),),
        now=NOW,
    )
    assert dependencies.calls == ["activation"]


@pytest.mark.asyncio
async def test_unavailable_package_produces_zero_notification_sends() -> None:
    dependencies = Dependencies()
    dependencies.available = False
    producer = CostGovernanceNotificationProducer(
        activation=dependencies,
        disclosure=dependencies,
        dispatcher=dependencies,
        pseudonym_key=bytes(range(32)),
    )
    assert not await producer.dispatch(
        destination_scope="governance",
        correlation_id="cost-1",
        records=(_record(),),
        now=NOW,
    )
    assert dependencies.calls == ["activation"]


@pytest.mark.asyncio
async def test_hidden_policy_produces_zero_notification_sends() -> None:
    dependencies = Dependencies()
    dependencies.policy = DISCLOSURE_PRESETS["hidden"]
    producer = CostGovernanceNotificationProducer(
        activation=dependencies,
        disclosure=dependencies,
        dispatcher=dependencies,
    )
    assert not await producer.dispatch(
        destination_scope="governance",
        correlation_id="cost-1",
        records=(_record(),),
        now=NOW,
    )
    assert dependencies.calls == ["activation", "disclosure"]


@pytest.mark.asyncio
async def test_masked_notification_uses_server_transformer_and_distinct_category() -> None:
    dependencies = Dependencies()
    producer = CostGovernanceNotificationProducer(
        activation=dependencies,
        disclosure=dependencies,
        dispatcher=dependencies,
        pseudonym_key=bytes(range(32)),
    )
    assert await producer.dispatch(
        destination_scope="governance",
        correlation_id="cost-1",
        records=(_record(),),
        now=NOW,
    )
    assert dependencies.calls == ["activation", "disclosure", "dispatch"]
    message = dependencies.messages[0]
    assert message.category == "cost_governance"
    assert message.metadata["producer"] == "fdai-cost-governance"
    assert "private-resource" not in message.body_markdown
    assert "amount_exact" not in message.body_markdown


@pytest.mark.asyncio
async def test_amount_hidden_policy_preserves_allowed_exact_identity() -> None:
    dependencies = Dependencies()
    dependencies.policy = CostDisclosurePolicy(
        granularity=CostGranularity.RESOURCE,
        identity_visibility=CostIdentityVisibility.EXACT,
        amount_precision=CostAmountPrecision.NONE,
    )
    producer = CostGovernanceNotificationProducer(
        activation=dependencies,
        disclosure=dependencies,
        dispatcher=dependencies,
    )

    assert await producer.dispatch(
        destination_scope="governance",
        correlation_id="cost-identity-only",
        records=(_record(),),
        now=NOW,
    )
    message = dependencies.messages[0]
    assert "private-resource" in message.body_markdown
    assert '"amount_' not in message.body_markdown
