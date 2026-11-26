"""Shared deterministic helpers for provider-specific notification rendering."""

from __future__ import annotations

_TRUNCATION_MARKER = " [truncated]"


def truncate_with_marker(value: str, *, limit: int) -> tuple[str, bool]:
    """Bound text without hiding that provider-specific truncation occurred."""

    if limit <= len(_TRUNCATION_MARKER):
        raise ValueError("rendering limit MUST exceed the truncation marker length")
    if len(value) <= limit:
        return value, False
    return f"{value[: limit - len(_TRUNCATION_MARKER)]}{_TRUNCATION_MARKER}", True


__all__ = ["truncate_with_marker"]
