"""Provider-neutral inputs for post-execution effect reconciliation requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from fdai.shared.contracts.models import Action

from .reconciliation_binding import ResolvedReconciliationArtifacts
from .reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectObservationEnvelope,
)


@dataclass(frozen=True, slots=True)
class ExecutedActionObservation:
    """One independent observation and authenticated context for a completed dispatch."""

    evidence: EffectObservationEnvelope
    observation_context: AuthenticatedObservationContext
    deadline: datetime
    evaluated_at: datetime


class ReconciliationRequestProductionStatus(StrEnum):
    """Bounded outcome of one post-execution request-production attempt."""

    PUBLISHED = "published"
    NOT_APPLICABLE = "not_applicable"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class ReconciliationRequestProduction:
    """No-authority receipt for one producer decision."""

    status: ReconciliationRequestProductionStatus
    reason_code: str
    reconciliation_id: str | None = None


class ExecutedActionReconciliationArtifactSource(Protocol):
    """Resolve an existing exact V2 plan for one Action, or decline legacy actions."""

    async def resolve(self, action: Action) -> ResolvedReconciliationArtifacts | None: ...


class ExecutedActionObservationSource(Protocol):
    """Observe an executed V2 plan through an identity independent from its executor."""

    async def observe(
        self,
        *,
        action: Action,
        artifacts: ResolvedReconciliationArtifacts,
        execution_outcome: str,
        execution_receipt_ref: str | None,
        correlation_id: str,
    ) -> ExecutedActionObservation | None: ...


class EffectReconciliationRequestSink(Protocol):
    """Produce at most one typed reconciliation request after ordinary dispatch."""

    async def __call__(
        self,
        action: Action,
        execution_outcome: str,
        execution_receipt_ref: str | None,
    ) -> ReconciliationRequestProduction: ...


__all__ = [
    "EffectReconciliationRequestSink",
    "ExecutedActionObservation",
    "ExecutedActionObservationSource",
    "ExecutedActionReconciliationArtifactSource",
    "ReconciliationRequestProduction",
    "ReconciliationRequestProductionStatus",
]
