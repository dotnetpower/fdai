"""A proposal that was never notified has no dispatch plan; that is a typed, recoverable state."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.delivery.persistence.postgres_notification_delivery import (
    NotificationDispatchPlanMissingError,
    PostgresNotificationDeliveryStore,
    _fetch_required,
)


async def test_missing_plan_raises_the_typed_error_that_is_still_a_runtime_error() -> None:
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone = AsyncMock(return_value=None)
    connection.execute = AsyncMock(return_value=cursor)

    with pytest.raises(NotificationDispatchPlanMissingError, match="does not exist"):
        await _fetch_required(
            connection, "SELECT 1", (), "plan does not exist", NotificationDispatchPlanMissingError
        )
    with pytest.raises(RuntimeError) as other:
        await _fetch_required(connection, "SELECT 1", (), "other row is missing")
    assert not isinstance(other.value, NotificationDispatchPlanMissingError)


async def test_snapshot_of_an_unknown_audit_identity_raises_the_typed_error() -> None:
    store = PostgresNotificationDeliveryStore.__new__(PostgresNotificationDeliveryStore)
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone = AsyncMock(return_value=None)
    connection.execute = AsyncMock(return_value=cursor)

    with pytest.raises(NotificationDispatchPlanMissingError):
        await store._snapshot(connection, "audit-id", datetime(2026, 11, 4, tzinfo=UTC))
