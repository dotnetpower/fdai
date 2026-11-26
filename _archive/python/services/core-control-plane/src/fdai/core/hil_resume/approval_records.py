"""Canonical helpers for durable HIL approval park records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.core.oncall import OnCallResolution
from fdai.shared.providers.hil_channel import HilDecision

_PARK_PREFIX = "hil_park:"
# Only these decisions may end a park; PENDING or any unknown value never changes one.
_RESOLVABLE_DECISIONS = frozenset({HilDecision.APPROVE, HilDecision.REJECT, HilDecision.TIMEOUT})


def park_key(approval_id: str) -> str:
    return f"{_PARK_PREFIX}{approval_id}"


def resolvable_decision(decision: object) -> HilDecision | None:
    """Return the terminal decision a park may resolve with, or ``None`` for any other value."""
    if not isinstance(decision, str):
        return None
    try:
        parsed = HilDecision(decision)
    except ValueError:
        return None
    return parsed if parsed in _RESOLVABLE_DECISIONS else None


def approval_expired(parked: Mapping[str, Any], *, now: datetime) -> bool:
    context = parked.get("approval_context")
    if not isinstance(context, Mapping):
        return True
    raw = context.get("expires_at")
    if not isinstance(raw, str) or not raw:
        return True
    try:
        expires_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return expires_at.tzinfo is None or expires_at <= now
    except ValueError:
        return True


def on_call_detail(resolution: OnCallResolution | None) -> dict[str, Any] | None:
    """Serialize a bounded, secret-free on-call resolution for audit and replay."""
    if resolution is None:
        return None
    return {
        "rotation": resolution.rotation,
        "primary_oid": resolution.primary_oid,
        "secondary_oid": resolution.secondary_oid,
        "from_schedule": resolution.from_schedule,
        "fallback_reason": resolution.fallback_reason,
    }
