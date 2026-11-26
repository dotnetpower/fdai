"""Explicit timezone-bearing timestamp inputs for measurement wire contracts."""

from __future__ import annotations

from datetime import datetime


def measurement_timestamp_input(value: object) -> datetime | str:
    """Reject implicit Unix-epoch coercion while preserving aware source instants."""
    if not isinstance(value, (datetime, str)):
        raise ValueError("measurement timestamps require aware datetime or ISO 8601 text")
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError:
        raise ValueError("measurement timestamp text is not ISO 8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("measurement timestamps require an explicit timezone")
    return value
