"""Authoritative current-revision reads for one managed target."""

from __future__ import annotations

from typing import Protocol


class TargetRevisionReader(Protocol):
    """Read the provider's exact current revision of one target resource."""

    async def read_revision(self, target_ref: str) -> str | None:
        """Return the current revision digest, or ``None`` when it cannot be established."""
        ...


__all__ = ["TargetRevisionReader"]
