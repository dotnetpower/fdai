"""Durable HIL decision transport and autonomous recovery tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.delivery.chatops.hil_decision import (
    HilDecisionDeliveryRecovery,
    HilDecisionRecoveryConfig,
)
from fdai.shared.providers.hil_registry import HilApprovalDecision, HilPendingItem
from fdai.shared.providers.testing.hil_registry import InMemoryHilApprovalRegistry


def _pending() -> HilPendingItem:
    return HilPendingItem(
        idempotency_key="idem-1",
        approval_id="approval-1",
        event_id="event-1",
        action_id="action-1",
        action_kind="remediate.tag-add",
        target_resource_ref="resource:example/one",
        reason="Approval required.",
        submitter_oid="submitter-1",
    )


async def _record_decision() -> InMemoryHilApprovalRegistry:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    await registry.record_decision(
        idempotency_key="idem-1",
        decision=HilApprovalDecision.APPROVE,
        approver_oid="approver-1",
        decided_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    return registry


async def test_recovery_drains_durable_undelivered_receipt() -> None:
    registry = await _record_decision()
    published = []

    async def publisher(receipt):  # type: ignore[no-untyped-def]
        published.append(receipt)

    recovery = HilDecisionDeliveryRecovery(registry=registry, publisher=publisher)

    assert await recovery.drain_once() == 1
    assert len(published) == 1
    assert registry.resolved[0].delivered is True
    assert registry.resolved[0].delivery_attempts == 1
    assert await recovery.drain_once() == 0
    assert len(published) == 1


async def test_recovery_abandons_after_persisted_attempt_ceiling() -> None:
    registry = await _record_decision()

    async def publisher(_receipt):  # type: ignore[no-untyped-def]
        raise RuntimeError("broker unavailable")

    recovery = HilDecisionDeliveryRecovery(
        registry=registry,
        publisher=publisher,
        config=HilDecisionRecoveryConfig(
            interval_seconds=1,
            publish_timeout_seconds=1,
            max_delivery_attempts=2,
        ),
    )

    assert await recovery.drain_once() == 0
    assert registry.resolved[0].delivery_attempts == 1
    assert registry.resolved[0].delivery_abandoned is False
    assert await recovery.drain_once() == 0
    assert registry.resolved[0].delivery_attempts == 2
    assert registry.resolved[0].delivery_abandoned is True
    assert await registry.list_undelivered() == ()


async def test_recovery_start_drains_then_stops_cleanly() -> None:
    registry = await _record_decision()
    delivered = asyncio.Event()

    async def publisher(_receipt):  # type: ignore[no-untyped-def]
        delivered.set()

    recovery = HilDecisionDeliveryRecovery(
        registry=registry,
        publisher=publisher,
        config=HilDecisionRecoveryConfig(interval_seconds=60),
    )

    await recovery.start()
    await asyncio.wait_for(delivered.wait(), timeout=1)
    await recovery.stop()

    assert registry.resolved[0].delivered is True


@pytest.mark.parametrize(
    "config",
    [
        HilDecisionRecoveryConfig(interval_seconds=1),
        HilDecisionRecoveryConfig(publish_timeout_seconds=1),
        HilDecisionRecoveryConfig(max_delivery_attempts=1),
        HilDecisionRecoveryConfig(batch_size=1),
    ],
)
def test_recovery_config_accepts_positive_bounds(config: HilDecisionRecoveryConfig) -> None:
    assert config.interval_seconds > 0
