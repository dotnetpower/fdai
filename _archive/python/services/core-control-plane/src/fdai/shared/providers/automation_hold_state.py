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


@runtime_checkable
class HoldReleaseAuthorizationReader(Protocol):
    """Return the dispatch authorization one exact workflow step holds.

    Expected lineage MUST come from the authorization bound when the hold was
    released for that step, or from the hold-scoped authorization an approved
    recovery step received, never from whatever hold record happens to be
    current at dispatch time. Deriving it from the current record would make
    the fence agree with any reissued-and-re-released hold.
    """

    async def read_dispatch_authorization(
        self,
        *,
        target_ref: str,
        process_id: str,
        step_id: str,
    ) -> Mapping[str, Any] | None:
        """Return the durable authorization, or ``None`` when none exists.

        Implementations MUST fail closed by raising rather than returning
        ``None`` when an authorization exists but cannot be read.
        """
        ...


__all__ = ["AutomationHoldStateReader", "HoldReleaseAuthorizationReader"]
