"""Provider-neutral contract for one authoritative exact Resource state read.

The read supplies the current lifecycle state of one already-authorized Resource so a typed answer
can cover a change the graph has not reconciled yet. It is read-only evidence: it never mutates the
graph, grants execution authority, or replaces reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ExactResourceStateUnavailableError(RuntimeError):
    """The provider could not return an authoritative state, such as on throttling or outage."""


@dataclass(frozen=True, slots=True)
class ExactResourceStateReading:
    """One authoritative state with the provider's own time and its evidence reference."""

    resource_ref: str
    resource_type: str
    state: str
    provider_time: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.resource_ref or not self.resource_type or not self.state.strip():
            raise ValueError("exact Resource state reading MUST name its Resource and state")
        if self.provider_time.tzinfo is None:
            raise ValueError("exact Resource state provider_time MUST be timezone-aware")
        if not self.evidence_ref.startswith("arm-state:sha256:"):
            raise ValueError("exact Resource state evidence_ref MUST be a content digest")


class ExactResourceStateReader(Protocol):
    """Read one Resource's state from its authoritative provider, or return none."""

    def supports(self, resource_type: str) -> bool: ...

    async def read_state(
        self,
        *,
        resource_ref: str,
        resource_type: str,
        provider_ref: str,
        timeout_seconds: float,
    ) -> ExactResourceStateReading | None: ...


__all__ = [
    "ExactResourceStateReader",
    "ExactResourceStateReading",
    "ExactResourceStateUnavailableError",
]
