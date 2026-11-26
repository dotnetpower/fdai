"""Shared validation for explicit action-outcome audit records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

MAX_OUTCOME_FUTURE_SKEW = timedelta(minutes=5)


def accepted_outcome_timestamp(
    observed_at: Any,
    *,
    recorded_at: Any,
) -> datetime | None:
    """Return a valid observed timestamp relative to its durable audit timestamp."""
    observed = _aware_datetime(observed_at)
    recorded = _aware_datetime(recorded_at)
    if observed is None or recorded is None:
        return None
    if observed.astimezone(UTC) > recorded.astimezone(UTC) + MAX_OUTCOME_FUTURE_SKEW:
        return None
    return observed


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = ["MAX_OUTCOME_FUTURE_SKEW", "accepted_outcome_timestamp"]
