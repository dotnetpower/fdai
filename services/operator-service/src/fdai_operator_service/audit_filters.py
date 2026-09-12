"""Parse bounded audit drill-down filters without interpreting operational intent."""

from __future__ import annotations

import re


def audit_window(value: str | None) -> int | None:
    """Parse the Console's day-window syntax; range enforcement stays in AuditQuery."""
    if value is None:
        return None
    if re.fullmatch(r"[1-9][0-9]{0,2}d", value) is None:
        raise ValueError("audit window MUST use 1d through 999d")
    return int(value[:-1])


def audit_sequence(value: str | None) -> int | None:
    """Parse an exact positive sequence without float or exponent coercion."""
    if value is None:
        return None
    if re.fullmatch(r"[1-9][0-9]{0,18}", value) is None:
        raise ValueError("audit sequence MUST be a positive bigint")
    return int(value)
