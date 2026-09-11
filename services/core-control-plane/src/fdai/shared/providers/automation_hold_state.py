"""Provider-neutral automation-hold state reads for dispatch fencing.

The executor MUST re-observe hold state inside its own logical-target lock
immediately before provider invocation (#640). This seam keeps that read
provider-neutral: it returns raw evidence, never a decision, and never grants
execution, release, or approval authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AutomationHoldStateReader(Protocol):
    """Return the raw automation-hold record for one logical target."""

    async def read_hold_record(self, *, target_ref: str) -> Mapping[str, Any] | None:
        """Return the durable hold record, or ``None`` when no hold exists.

        Implementations MUST fail closed by raising rather than returning
        ``None`` when the record exists but cannot be read, so a caller can
        distinguish "no hold" from "unreadable hold".
        """
        ...


__all__ = ["AutomationHoldStateReader"]
