"""Shared bounded outbox publication helpers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class PublicationClaim:
    owner: str
    claimed_at: str


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


def new_publication_claim_owner(agent_name: str) -> str:
    return f"{agent_name}:{uuid4().hex}"


def claim_matches(row: Mapping[str, Any], claim: PublicationClaim) -> bool:
    """Return whether a stored outbox row still carries this exact publication claim."""
    return (
        str(row.get("claim_owner") or "") == claim.owner
        and str(row.get("claimed_at") or "") == claim.claimed_at
    )


async def await_bounded_publication[T](awaitable: Awaitable[T], *, lease: timedelta) -> T:
    task = asyncio.ensure_future(awaitable)
    try:
        done, _pending = await asyncio.wait({task}, timeout=publish_timeout_seconds(lease))
    except asyncio.CancelledError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise
    if not done:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise TimeoutError("outbox publication timed out before claim lease expiry")
    return task.result()


async def publish_claimed_outbox[TClaim](
    claim: TClaim | None,
    *,
    publish: Callable[[], Awaitable[Any]],
    mark_published: Callable[[TClaim], Awaitable[bool | None]],
    release: Callable[[TClaim], Awaitable[None]],
    lease: timedelta,
) -> bool:
    if claim is None:
        return False
    try:
        await await_bounded_publication(publish(), lease=lease)
        marked = await asyncio.shield(mark_published(claim))
    except asyncio.CancelledError:
        if (task := asyncio.current_task()) is not None and not task.cancelling():
            await release(claim)
        raise
    except Exception:
        await release(claim)
        raise
    return marked is not False


__all__ = [
    "PublicationClaim",
    "await_bounded_publication",
    "claim_expired",
    "claim_matches",
    "new_publication_claim_owner",
    "publish_claimed_outbox",
    "publish_timeout_seconds",
]
