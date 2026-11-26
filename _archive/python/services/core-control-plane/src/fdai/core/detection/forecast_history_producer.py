"""Restate authoritative source reads as normalized forecast history with honest coverage.

Heimdall runs one producer per reviewed binding immediately before it collects forecast
history. The producer is never a second writer of action, change, lifecycle, or change-window
facts: it restates records another owner retained as `derived` transitions without execution
authority. Transitions are appended only from a clean read whose source positively attests the
exact window, identity, revision, pagination, current knowledge time, and (for stateful sources)
initial state, and only when every stored transition in the window is re-asserted by that read.
Every other outcome appends one incomplete checkpoint with bounded limitation tokens and no
transitions, so the collector keeps holding scoring.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from fdai.core.detection.forecast_history import ForecastHistoryBinding
from fdai.core.detection.forecast_history_chain import (
    ChainStep,
    anchor_instant,
    derive_state_chain,
    retained_limitations,
)
from fdai.core.detection.forecast_history_source import (
    EVENT_BASELINE_STATE,
    STATEFUL_FORECAST_HISTORY_KINDS,
    ForecastHistoryProducerBinding,
    ForecastHistorySource,
    ForecastSourceRead,
    ForecastSourceRecord,
    bounded_limitation,
    source_limitation_tokens,
)
from fdai.core.ontology_platform.state_transitions import (
    OperationalStateTransition,
    StateTransitionAuthority,
    StateTransitionBatch,
    StateTransitionCoverage,
    StateTransitionLane,
    StateTransitionStore,
)
from fdai.shared.providers.forecast_context import ForecastContextRequest

FORECAST_HISTORY_PRODUCER_ID = "heimdall.forecast-history-producer"
FORECAST_HISTORY_PRODUCER_VERSION = "1.0.0"
_MAX_RECORDS = 256
_MAX_RETAINED = 512
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ForecastHistoryProduction:
    """Receipt of one append; it is evidence of production, never scoring or execution."""

    kind: str
    complete: bool
    limitation: str | None
    appended: bool
    transition_count: int
    coverage_id: str
    scoring_eligible: Literal[False] = False
    execution_authority: Literal[False] = False


def validate_forecast_history_producer(
    binding: ForecastHistoryProducerBinding, history: ForecastHistoryBinding
) -> None:
    """Reject a producer mapping that does not restate exactly one reviewed collector mapping."""
    if (binding.kind, binding.access_scope_digest, binding.target_ref) != (
        history.kind,
        history.access_scope_digest,
        history.target_ref,
    ):
        raise ValueError("forecast history producer does not match its collector binding")
    if not set(binding.state_mapping.values()) <= set(history.to_states):
        raise ValueError("forecast history producer maps outside the reviewed states")
    if EVENT_BASELINE_STATE in history.to_states:
        raise ValueError("forecast history reviewed states cannot use the event baseline")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


class ForecastHistoryProducer:
    """Append one bounded batch per request; replay and restart never duplicate transitions."""

    def __init__(
        self,
        *,
        binding: ForecastHistoryProducerBinding,
        history: ForecastHistoryBinding,
        source: ForecastHistorySource,
        store: StateTransitionStore,
        source_timeout_seconds: float = 1.0,
    ) -> None:
        validate_forecast_history_producer(binding, history)
        if (
            isinstance(source_timeout_seconds, bool)
            or not math.isfinite(source_timeout_seconds)
            or not 0 < source_timeout_seconds <= 5
        ):
            raise ValueError("forecast history source timeout MUST be in (0, 5]")
        self._binding = binding
        self._history = history
        self._source = source
        self._store = store
        self._source_timeout_seconds = source_timeout_seconds
        self._stateful = binding.kind in STATEFUL_FORECAST_HISTORY_KINDS
        self.target_digest = hashlib.sha256(history.target_ref.encode()).hexdigest()

    @property
    def kind(self) -> str:
        return self._binding.kind

    @property
    def access_scope_digest(self) -> str:
        return self._history.access_scope_digest

    async def produce(self, request: ForecastContextRequest) -> ForecastHistoryProduction:
        """Read the source as known at `request.as_of` and append coverage plus new transitions.

        A source read that exceeds its own deadline is `source_unavailable`, so the incomplete
        checkpoint is still appended within the caller's per-kind budget.
        """
        history = self._history
        if (request.access_scope_digest, request.target_digest) != (
            history.access_scope_digest,
            self.target_digest,
        ):
            raise ValueError("forecast history production request is outside its binding")
        recorded_at = request.as_of
        lookback = timedelta(seconds=history.lookback_seconds if self._stateful else 0)
        start_at = request.horizon_started_at - lookback
        end_at = request.horizon_ended_at
        tokens: set[str] = set()
        derived: tuple[OperationalStateTransition, ...] = ()
        initial: str | None = None
        watermark, evidence_ref = "unavailable", f"forecast-history-source:{self.kind}:unavailable"
        try:
            async with asyncio.timeout(self._source_timeout_seconds):
                read = await self._source.read(
                    subject_ref=history.target_ref,
                    start_at=start_at,
                    end_at=end_at,
                    known_at=recorded_at,
                )
            if not isinstance(read, ForecastSourceRead):
                raise TypeError("forecast history source returned an untyped read")
            watermark = read.checkpoint.watermark
            evidence_ref = read.checkpoint.evidence_ref
            derived, initial = self._derive(read, start_at, end_at, request, tokens)
        except Exception as exc:
            _LOGGER.warning(
                "forecast_history_source_unavailable",
                extra={"kind": self.kind, "error_type": type(exc).__name__},
            )
            tokens.add("source_unavailable")
        fresh: tuple[OperationalStateTransition, ...] = ()
        if not tokens:
            fresh = await self._reconcile(derived, initial, start_at, end_at, recorded_at, tokens)
        window = (start_at, end_at, recorded_at, watermark, evidence_ref)
        batch = self._batch(fresh, *window, tokens)
        try:
            appended = await self._store.append(batch)
        except ValueError:
            tokens.add("conflicting_retained_record")
            fresh = ()
            batch = self._batch((), *window, tokens)
            appended = await self._store.append(batch)
        coverage = batch.coverage[0]
        return ForecastHistoryProduction(
            kind=self.kind,
            complete=coverage.complete,
            limitation=coverage.limitation,
            appended=appended,
            transition_count=len(fresh),
            coverage_id=coverage.coverage_id,
        )

    def _derive(
        self,
        read: ForecastSourceRead,
        start_at: datetime,
        end_at: datetime,
        request: ForecastContextRequest,
        tokens: set[str],
    ) -> tuple[tuple[OperationalStateTransition, ...], str | None]:
        """Derive the complete window from a clean read, or nothing when any limitation exists."""
        history, checkpoint, recorded_at = self._history, read.checkpoint, request.as_of
        if (checkpoint.source_identity, checkpoint.source_revision, checkpoint.subject_ref) != (
            history.source_identity,
            history.source_revision,
            history.target_ref,
        ):
            tokens.add("source_identity_mismatch")
            return (), None
        if not checkpoint.complete:
            tokens.update(source_limitation_tokens(checkpoint.limitation))
        if checkpoint.coverage_start_at > start_at or checkpoint.coverage_end_at < end_at:
            tokens.add("coverage_window_short")
        if checkpoint.known_at != recorded_at:
            tokens.add(
                "coverage_time_invalid"
                if checkpoint.known_at > recorded_at
                else "source_knowledge_stale"
            )
        if not read.exhausted or len(read.records) > _MAX_RECORDS:
            tokens.add("result_limit")
        admitted: dict[tuple[str, str], ForecastSourceRecord] = {}
        for record in read.records[:_MAX_RECORDS]:
            if (
                record.subject_ref != history.target_ref
                or not start_at <= record.effective_at <= end_at
                or record.recorded_at > recorded_at
            ):
                tokens.add("record_out_of_scope")
            elif record.pending:
                tokens.add("pending_source_record")
            elif admitted.setdefault((record.source_event_id, record.source_revision), record) != (
                record
            ):
                tokens.add("conflicting_source_record")
        if self._stateful and len({event for event, _revision in admitted}) != len(admitted):
            tokens.add("conflicting_source_record")
        mapped: list[tuple[ForecastSourceRecord, str]] = []
        for _key, record in sorted(admitted.items()):
            state = self._binding.state_mapping.get(record.source_state)
            if state is None:
                tokens.add("unmapped_source_state")
            else:
                mapped.append((record, state))
        if tokens:
            return (), None
        if not self._stateful:
            steps = tuple(
                ChainStep(
                    ("event", record.source_event_id, record.source_revision),
                    EVENT_BASELINE_STATE,
                    state,
                    record.effective_at,
                    record.evidence_ref,
                )
                for record, state in mapped
            )
            return tuple(self._transition(step, recorded_at) for step in steps), None
        initial = self._binding.state_mapping.get(checkpoint.initial_state or "")
        if initial is None:
            tokens.add(
                "initial_state_unknown"
                if checkpoint.initial_state is None
                else "unmapped_source_state"
            )
            return (), None
        chain = derive_state_chain(
            mapped,
            initial=initial,
            initial_ref=checkpoint.initial_state_ref or checkpoint.evidence_ref,
            start_at=start_at,
            anchor_at=anchor_instant(
                request.horizon_started_at, step_seconds=history.lookback_seconds
            ),
            tokens=tokens,
        )
        return tuple(self._transition(step, recorded_at) for step in chain), initial

    def _transition(self, step: ChainStep, recorded_at: datetime) -> OperationalStateTransition:
        history = self._history
        key = _digest(
            [
                "forecast-history-transition:v1",
                history.kind,
                history.access_scope_digest,
                history.target_ref,
                history.state_type,
                history.source_identity,
                history.source_revision,
                *step.identity,
            ]
        )
        return OperationalStateTransition.create(
            idempotency_key=f"forecast-history:v1:{key}",
            subject_ref=history.target_ref,
            subject_type=self._binding.subject_type,
            state_type=history.state_type,
            from_state=step.from_state,
            to_state=step.to_state,
            lane=StateTransitionLane.DERIVED,
            authority=StateTransitionAuthority.DETERMINISTIC_FUNCTION,
            effective_at=step.effective_at,
            evidence_cutoff=recorded_at,
            recorded_at=recorded_at,
            source_identity=history.source_identity,
            source_revision=history.source_revision,
            producer_id=FORECAST_HISTORY_PRODUCER_ID,
            producer_version=FORECAST_HISTORY_PRODUCER_VERSION,
            freshness_ceiling_seconds=history.freshness_seconds,
            completeness_basis_points=10_000,
            evidence_refs=(step.evidence_ref,),
        )

    async def _reconcile(
        self,
        derived: tuple[OperationalStateTransition, ...],
        initial: str | None,
        start_at: datetime,
        end_at: datetime,
        recorded_at: datetime,
        tokens: set[str],
    ) -> tuple[OperationalStateTransition, ...]:
        """Require the stored window to be re-asserted, then return only transitions it lacks."""
        retained = await self._store.read(
            subject_refs=(self._history.target_ref,),
            state_types=(self._history.state_type,),
            to_states=None,
            start_at=start_at,
            end_at=end_at,
            known_at=recorded_at,
            limit=_MAX_RETAINED,
        )
        if "result_limit" in (retained.limitation or ""):
            tokens.add("retained_history_limit")
            return ()
        tokens.update(retained_limitations(retained.transitions, derived, initial=initial))
        if tokens:
            return ()
        stored = {item.idempotency_key for item in retained.transitions}
        return tuple(item for item in derived if item.idempotency_key not in stored)

    def _batch(
        self,
        transitions: tuple[OperationalStateTransition, ...],
        start_at: datetime,
        end_at: datetime,
        recorded_at: datetime,
        watermark: str,
        evidence_ref: str,
        tokens: set[str],
    ) -> StateTransitionBatch:
        history = self._history
        limitation = bounded_limitation(tokens)
        coverage = StateTransitionCoverage.create(
            subject_ref=history.target_ref,
            state_type=history.state_type,
            coverage_start_at=start_at,
            coverage_end_at=end_at,
            recorded_at=recorded_at,
            source_identity=history.source_identity,
            source_revision=history.source_revision,
            watermark=watermark,
            evidence_ref=evidence_ref,
            complete=limitation is None,
            limitation=limitation,
        )
        return StateTransitionBatch.create(
            transitions=transitions, coverage=(coverage,), recorded_at=recorded_at
        )


__all__ = [
    "FORECAST_HISTORY_PRODUCER_ID",
    "FORECAST_HISTORY_PRODUCER_VERSION",
    "ForecastHistoryProducer",
    "ForecastHistoryProduction",
    "validate_forecast_history_producer",
]
