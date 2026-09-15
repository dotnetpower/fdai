"""Read-only cross-service handover goal projection, with bounded pagination."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class HandoverGoalProjectionReader(Protocol):
    """Return content-free observations, not an assignment or acceptance capability.

    Implementations expose only Operator-owned goal records and have no mutation method.
    Invalid rows remain visible for per-record held auditing; unavailable I/O must propagate.
    """

    async def read_page(
        self, *, limit: int, offset: int
    ) -> tuple[Sequence[Mapping[str, Any]], int]: ...


__all__ = ["HandoverGoalProjectionReader"]
