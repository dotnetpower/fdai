"""Dependency contracts for the service-local Operator operations family."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class ProjectionUnavailableError(RuntimeError):
    """An authoritative projection cannot satisfy the bounded read."""


class ProposalConflictError(RuntimeError):
    """An idempotency key already names a different durable proposal."""


@dataclass(frozen=True, slots=True)
class ProjectionQuery:
    """One authenticated, bounded query against an injected projection reader."""

    operation: str
    principal_id: str
    path: Mapping[str, str]
    params: Mapping[str, tuple[str, ...]]
    limit: int
    cursor: str | None


class ProjectionReader(Protocol):
    """Read authoritative operation projections without provider access in routes."""

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        """Return a JSON-compatible projection or raise unavailable."""
        ...


@dataclass(frozen=True, slots=True)
class EventProposal:
    """A non-authoritative event proposal persisted before broker publication."""

    operation: str
    principal_id: str | None
    idempotency_key: str
    correlation_id: str | None
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProposalReceipt:
    """Durable acceptance receipt that makes no execution claim."""

    request_id: str
    correlation_id: str | None
    dispatch_status: str
    accepted_at: str
    durably_queued: bool = True

    def to_dict(self) -> dict[str, object]:
        """Render the stable proposal acceptance envelope."""
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "dispatch_status": self.dispatch_status,
            "accepted_at": self.accepted_at,
            "durably_queued": self.durably_queued,
        }


class EventProposalWriter(Protocol):
    """Atomically persist an event proposal and its outbox receipt."""

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        """Return only after the proposal is durably queued."""
        ...


@dataclass(frozen=True, slots=True)
class ReplayQuery:
    """One principal-scoped request for durable ordered stream records."""

    stream: str
    principal_id: str
    after_sequence: int | None
    limit: int


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """One durable SSE record with a monotonic replay sequence."""

    sequence: int
    event: str
    data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ReplayBatch:
    """A bounded replay page and durable source watermark."""

    events: tuple[ReplayEvent, ...]
    watermark: int


class DurableReplayReader(Protocol):
    """Read persisted stream events; transient fan-out is not authoritative."""

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        """Return events ordered after the requested durable sequence."""
        ...


class WebhookVerifier(Protocol):
    """Verify a bounded webhook body without exposing secret material."""

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Return true only for an authenticated webhook request."""
        ...


__all__ = [
    "DurableReplayReader",
    "EventProposal",
    "EventProposalWriter",
    "ProjectionQuery",
    "ProjectionReader",
    "ProjectionUnavailableError",
    "ProposalConflictError",
    "ProposalReceipt",
    "ReplayBatch",
    "ReplayEvent",
    "ReplayQuery",
    "WebhookVerifier",
]
