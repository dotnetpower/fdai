"""Provider seam for dispatching one normalized operator ActionProposal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class OperatorProposalDispatch:
    """Truthful, surface-neutral view of one dispatched operator proposal.

    ``decision`` is the gate word the control loop recorded (``shadow``,
    ``auto``, ``hil``, ``deny``, or ``abstain``). ``approval_ref`` is set only
    when the decision parked for a distinct approver, and ``process_ref`` only
    when the request started a multi-step Workflow. Neither reference carries an
    executor identity.
    """

    decision: str
    approval_ref: str | None = None
    process_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.decision.strip():
            raise ValueError("OperatorProposalDispatch.decision MUST be non-empty")


@runtime_checkable
class OperatorProposalDispatcher(Protocol):
    """Hand one raw operator ActionProposal to the authoritative control path."""

    async def dispatch(self, proposal: Mapping[str, Any]) -> OperatorProposalDispatch:
        """Publish the proposal, or raise so the caller records failed dispatch.

        The binding adapter normalizes the proposal at event ingest and lets the
        control loop judge, gate, and route it. It never executes the action
        directly and never grants the caller an executor identity.
        """
        ...


__all__ = ["OperatorProposalDispatch", "OperatorProposalDispatcher"]
