"""Shared bounded outbox publication helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime, timedelta


def claim_expired(*, claimed_at: object, now: datetime, lease: timedelta) -> bool:
    if not isinstance(claimed_at, str) or not claimed_at:
        return True
    try:
        parsed = datetime.fromisoformat(claimed_at)
    except ValueError:
        return True
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return True
    return now - parsed >= lease


def publish_timeout_seconds(lease: timedelta) -> float:
    return max(0.001, lease.total_seconds() / 2)


async def await_bounded_publication[T](awaitable: Awaitable[T], *, lease: timedelta) -> T:
    async with asyncio.timeout(publish_timeout_seconds(lease)):
        return await awaitable


__all__ = ["await_bounded_publication", "claim_expired", "publish_timeout_seconds"]
