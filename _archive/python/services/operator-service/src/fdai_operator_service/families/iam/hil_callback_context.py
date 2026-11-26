"""Original approval context seam for replay-safe callback decisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HilCallbackContext:
    """Immutable callback fields copied from the original parked approval."""

    approval_id: str
    correlation_id: str
    idempotency_key: str
    action_hash: str
    expires_at: datetime
    submitter_oid: str
    metadata: Mapping[str, str] = field(default_factory=dict)


class HilCallbackContextReader(Protocol):
    """Read original callback context even after the approval becomes terminal."""

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None: ...


__all__ = ["HilCallbackContext", "HilCallbackContextReader"]
