"""Serialized cross-vertical candidate intake for Forseti."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from fdai.agents._framework import forseti_durability as _durability
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.cross_vertical_candidates import (
    CandidateIntakeState,
    CrossVerticalCandidateAccumulator,
)
from fdai.core.decision_case import DomainOptionEvidence, conflicting_objective_effects
from fdai.core.operational_context import SourceFreshness


class CrossVerticalIntakeHost(Protocol):
    _cross_vertical_candidates: CrossVerticalCandidateAccumulator
    _cross_vertical_timeout_tasks: dict[str, asyncio.Task[None]]
    _cross_vertical_timeout_deadlines: dict[str, float]
    _pending_arbitration_principals: BoundedLruDict[str, dict[str, str]]

    def record_behavior(self, name: str, amount: int = 1) -> None: ...

    def _start_cross_vertical_timeout(
        self,
        correlation_id: str,
        *,
        delay_seconds: float | None = None,
    ) -> None: ...

    async def _cancel_cross_vertical_timeout(self, timeout: str | asyncio.Task[None]) -> None: ...

    async def _close_cross_vertical_candidates(self, closures: tuple[Any, ...]) -> None: ...

    async def _emit_arbitration_request(
        self,
        *,
        resource_id: Any,
        advice: dict[str, str],
        correlation_id: str,
        impacts: dict[str, float] | None = None,
        arguments_by_domain: dict[str, dict[str, object]] | None = None,
        observed_at: str = "",
        change_assessment: dict[str, Any] | None = None,
        source_freshness: tuple[SourceFreshness, ...] = (),
        evidence_by_domain: dict[str, DomainOptionEvidence] | None = None,
        objective_conflicts: tuple[tuple[str, str, str], ...] = (),
    ) -> dict[str, Any]: ...


async def ingest_cross_vertical_candidate_locked(
    host: CrossVerticalIntakeHost,
    topic: str,
    payload: dict[str, Any],
    correlation_id: str,
) -> None:
    if correlation_id and await _durability.durable_cross_vertical_completed(host, correlation_id):
        host._cross_vertical_candidates.mark_completed(correlation_id)
        host.record_behavior("cross_vertical_candidate:duplicate")
        return
    intake = host._cross_vertical_candidates.ingest(topic, payload)
    if intake.state is CandidateIntakeState.DUPLICATE:
        host.record_behavior("cross_vertical_candidate:duplicate")
        return
    if intake.state is CandidateIntakeState.HIL:
        for closure in intake.closures:
            await _durability.mark_cross_vertical_completed(
                host, closure.correlation_id, closure.reason
            )
        await host._close_cross_vertical_candidates(intake.closures)
        return
    if intake.state is CandidateIntakeState.PENDING:
        await _durability.persist_cross_vertical_pending(host, intake.correlation_id)
        if intake.correlation_id not in host._cross_vertical_timeout_deadlines:
            host._start_cross_vertical_timeout(intake.correlation_id)
        host.record_behavior("cross_vertical_candidate:pending")
        return

    batch = intake.batch
    if batch is None:  # pragma: no cover - CandidateIntake invariant
        raise RuntimeError("ready cross-vertical candidate intake has no batch")
    await _durability.mark_cross_vertical_completed(host, batch.correlation_id, "ready")
    await host._cancel_cross_vertical_timeout(batch.correlation_id)
    conflicts = conflicting_objective_effects(tuple(batch.evidence_by_domain.values()))
    if not conflicts:
        host.record_behavior("cross_vertical_candidate:no_conflict")
        return
    host._pending_arbitration_principals.set(
        batch.correlation_id,
        batch.principals_by_domain,
    )
    await host._emit_arbitration_request(
        resource_id=batch.resource_id,
        advice=batch.advice,
        correlation_id=batch.correlation_id,
        impacts=batch.impacts,
        observed_at=batch.observed_at,
        source_freshness=batch.source_freshness,
        evidence_by_domain=batch.evidence_by_domain,
        objective_conflicts=conflicts,
    )
    host.record_behavior("cross_vertical_candidate:ready")
