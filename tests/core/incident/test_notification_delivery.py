"""Atomic incident notification delivery-store tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.incident.notification_delivery import (
    InMemoryIncidentNotificationDeliveryStore,
    NotificationClaimStatus,
)

NOW = datetime(2026, 7, 15, tzinfo=UTC)


async def test_claim_lease_recovery_and_token_isolation() -> None:
    store = InMemoryIncidentNotificationDeliveryStore()
    first = await store.claim(audit_id="notice-1", now=NOW, lease_seconds=60)
    active = await store.claim(
        audit_id="notice-1",
        now=NOW + timedelta(seconds=30),
        lease_seconds=60,
    )
    recovered = await store.claim(
        audit_id="notice-1",
        now=NOW + timedelta(seconds=61),
        lease_seconds=60,
    )

    assert first.status is NotificationClaimStatus.CLAIMED
    assert active.status is NotificationClaimStatus.IN_PROGRESS
    assert recovered.status is NotificationClaimStatus.CLAIMED
    assert first.token != recovered.token
    assert first.token is not None
    assert recovered.token is not None

    await store.release(audit_id="notice-1", token=first.token)
    with pytest.raises(RuntimeError, match="token mismatch"):
        await store.complete(audit_id="notice-1", token=first.token, at=NOW)
    await store.complete(audit_id="notice-1", token=recovered.token, at=NOW)

    sent = await store.claim(
        audit_id="notice-1",
        now=NOW + timedelta(seconds=62),
        lease_seconds=60,
    )
    assert sent.status is NotificationClaimStatus.SENT


async def test_claim_input_validation() -> None:
    store = InMemoryIncidentNotificationDeliveryStore()
    with pytest.raises(ValueError, match="audit_id"):
        await store.claim(audit_id="", now=NOW, lease_seconds=60)
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.claim(
            audit_id="notice-1",
            now=datetime(2026, 7, 15),
            lease_seconds=60,
        )
    with pytest.raises(ValueError, match=">= 1"):
        await store.claim(audit_id="notice-1", now=NOW, lease_seconds=0)
