"""Time helpers for durable ActionRun resource claims."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any


def lease_expiry(seconds: int) -> str:
    """Return the bounded claim expiry from the current UTC time."""

    return (datetime.now(tz=UTC) + timedelta(seconds=seconds)).isoformat()


def claim_lease_expiry(claim: Mapping[str, Any]) -> datetime:
    """Parse one claim expiry or return the earliest UTC instant."""

    raw = claim.get("lease_expires_at")
    if not isinstance(raw, str):
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else datetime.min.replace(tzinfo=UTC)


__all__ = ["claim_lease_expiry", "lease_expiry"]
