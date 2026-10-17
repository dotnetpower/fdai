"""Phase-4 continuous-measurement runners.

This module wires the two library-only components in
:mod:`fdai.core.measurement` into scheduled Container Apps Jobs:

- :class:`AutomatedBaselineRunner` - periodically re-executes the P0
  scenario set through the current control loop, feeds the observations
  into :class:`~fdai.core.measurement.regression.RegressionDetector`,
  and auto-demotes any ActionType whose regression is a guard-metric
  breach or a success-metric drop.
- :class:`PatternGrowthIntakeRunner` - drains new executed-action
  outcomes from the audit stream, applies the
  :func:`~fdai.core.measurement.pattern_growth.evaluate_intake`
  filter, and - on ``ACCEPTED`` - pushes the resulting pattern into the
  T1 library in **shadow** mode.

Design constraints
------------------

- Both runners run inside Container Apps Jobs; the concrete cron / event
  trigger lives in :mod:`infra/modules/measurement-runners`. Runners
  themselves are pure orchestration objects with no scheduler code.
- Neither runner ever **auto-promotes** an ActionType. A regression
  demotes; growth ingests shadow-only patterns whose
  ``historical_success_rate == 0.0`` so the T1 tier's
  ``min_success_rate`` floor keeps them out of execution until the
  reviewed promotion pipeline lifts them.
- Every terminal path writes an audit entry through the injected
  :class:`~fdai.shared.providers.state_store.StateStore`, matching
  the "every autonomous action MUST audit" invariant in
  ``coding-conventions.instructions.md``.
- ``core/`` never imports a concrete cloud SDK or delivery adapter -
  the scenario replayer, outcome source, pattern builder, and pattern
  library writer are all Protocols bound at the composition root
  (``check-core-imports.sh``).

Failure modes
-------------

- A scenario replayer that raises fails the run **closed**: no demotion,
  a single audited abort entry so an operator can page on it.
- A pattern builder that returns ``None`` (missing origin event, unable
  to embed) records an audited skip and continues - a single unreadable
  outcome MUST NOT stall the growth loop.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from fdai.core.assurance_twin.model_registry import RegistryUpdate
from fdai.core.measurement.pattern_growth import (
    IntakeDecision,
    IntakeOutcome,
    OutcomeRecord,
    evaluate_intake,
)
from fdai.core.measurement.pending_growth import PendingPatternGrowth, record_key
from fdai.core.measurement.regression import (
    MeasurementSample,
    RegressionDecision,
    RegressionDetector,
    RegressionOutcome,
)
from fdai.core.risk_gate.gate import ActionPromotionRegistry
from fdai.core.tiers.t1_lightweight.tier import LearnedAction
from fdai.shared.contracts.models import Mode, ResponseOutcome
from fdai.shared.providers.pattern_library_writer import PatternLibraryWriter
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.core.measurement.runners")


def _default_clock() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Seams - DI Protocols the two runners consume.
# ---------------------------------------------------------------------------


@runtime_checkable
class ScenarioReplayer(Protocol):
    """Replay the P0 scenario set + return per-ActionType :class:`MeasurementSample`.

    The replayer OWNS the composition of baseline vs treatment run -
    concrete implementations:

    1. Load the frozen P0 scenario set for a known
       ``scenario_set_version``.
    2. Drive each scenario through the current
       :class:`~fdai.core.control_loop.ControlLoop`.
    3. Look up the previously-recorded baseline (guard ceilings + success
       lower CI bounds) for the same scenario-set version.
    4. Fold both into per-ActionType
       :class:`~fdai.core.measurement.regression.MeasurementSample`
       instances the runner hands to the
       :class:`~fdai.core.measurement.regression.RegressionDetector`.

    Keeping this composition behind a Protocol lets ``core/`` avoid
    importing higher-level modules (ControlLoop) and keeps the runner
    unit-testable with a small in-memory fake.
    """

    scenario_set_version: str

    async def replay(self) -> Sequence[MeasurementSample]: ...


@runtime_checkable
class OutcomeSource(Protocol):
    """Stream of executed-action outcomes drained from the audit trail.

    A concrete implementation queries the audit store for entries whose
    ``action_kind`` matches an ActionType id and whose executor outcome
    is a successful execution, then yields the outcome record. Each
    yielded record is expected to carry the four fields the intake
    filter reads: ``was_auto``, ``was_verified``, ``was_rolled_back``.

    The Protocol returns an :class:`AsyncIterator`; the runner drains
    it once per invocation (Container Apps Jobs are short-lived; the
    scheduler triggers the runner every few minutes to pick up new
    outcomes).
    """

    def outcomes(self) -> AsyncIterator[OutcomeRecord]: ...


@runtime_checkable
class ResponseOutcomeSource(Protocol):
    """Stream standardized response outcomes from the audit trail."""

    def outcomes(self) -> AsyncIterator[ResponseOutcome]: ...


@runtime_checkable
class ChallengerUpdater(Protocol):
    """Update only a registered shadow challenger model."""

    async def update_from_outcome(self, outcome: ResponseOutcome) -> RegistryUpdate: ...


@runtime_checkable
class PatternBuilder(Protocol):
    """Turn an accepted outcome into a ``(vector, LearnedAction)`` pair.

    Concrete implementations reconstruct the origin event embedding
    from the audit trail (``events.payload``), rebuild the executed
    action's parameters, and compute the pattern signature. Return
    ``None`` when the source is terminally ineligible. Return
    :class:`DeferredPatternBuild` for evidence that may arrive later;
    the runner persists that work before acknowledging the source.

    Return values are **candidate** patterns: the runner enforces the
    shadow-first invariant by resetting ``success_rate`` and
    ``reuse_count`` before persisting.
    """

    async def build(
        self, record: OutcomeRecord
    ) -> tuple[Sequence[float], LearnedAction] | DeferredPatternBuild | None: ...


@dataclass(frozen=True, slots=True)
class DeferredPatternBuild:
    """Evidence may arrive later; this is neither success nor terminal failure."""

    reason: str


# ---------------------------------------------------------------------------
# AutomatedBaselineRunner - regression detection + auto-demote.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineRunReport:
    """Aggregate result for one :meth:`AutomatedBaselineRunner.run_once` call."""

    scenario_set_version: str
    sample_count: int
    regressions: tuple[RegressionDecision, ...] = field(default_factory=tuple)
    demoted_action_types: tuple[str, ...] = field(default_factory=tuple)
    aborted_reason: str | None = None

    @property
    def had_regression(self) -> bool:
        return bool(self.regressions)


class AutomatedBaselineRunner:
    """Scheduled runner: replay P0 scenarios, detect regressions, demote.

    Wired as a Container Apps Job on a daily cron (see
    ``infra/modules/measurement-runners``). One invocation performs
    exactly one full replay of the frozen scenario set - the scheduler,
    not this class, owns the cadence.

    Safety
    ------

    - **Never auto-promotes.** The only mutation to the promotion
      registry is a call to
      :meth:`~fdai.core.risk_gate.gate.ActionPromotionRegistry.demote`.
    - **Fail-closed on replayer errors.** A raised exception aborts the
      run without touching the registry, and records a single audited
      abort entry so an operator can investigate.
    - **Every terminal path audits.** Both ``pass``, ``regression``, and
      ``abort`` outcomes write a hash-chained audit entry.
    """

    __slots__ = (
        "_audit_store",
        "_clock",
        "_detector",
        "_persist_mode",
        "_registry",
        "_replayer",
    )

    def __init__(
        self,
        *,
        replayer: ScenarioReplayer,
        detector: RegressionDetector,
        registry: ActionPromotionRegistry,
        audit_store: StateStore,
        clock: Callable[[], datetime] | None = None,
        persist_mode: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._replayer = replayer
        self._detector = detector
        self._registry = registry
        self._audit_store = audit_store
        self._clock = clock or _default_clock
        self._persist_mode = persist_mode

    async def run_once(self) -> BaselineRunReport:
        """Execute one regression-detection cycle."""
        version = self._replayer.scenario_set_version
        try:
            samples = await self._replayer.replay()
        except Exception as exc:  # pragma: no cover - the abort path is tested
            reason = f"scenario_replay_failed:{type(exc).__name__}:{exc}"
            await self._write_run_audit(
                version=version,
                sample_count=0,
                regressions=(),
                demoted=(),
                aborted_reason=reason,
            )
            return BaselineRunReport(
                scenario_set_version=version,
                sample_count=0,
                aborted_reason=reason,
            )

        regressions: list[RegressionDecision] = []
        demoted: list[str] = []
        for sample in samples:
            decision = self._detector.evaluate(sample)
            if decision.outcome is RegressionOutcome.PASS:
                continue
            regressions.append(decision)
            record = self._registry.demote(sample.action_type_id)
            if self._persist_mode is not None:
                await self._persist_mode(sample.action_type_id)
            if record.mode is Mode.SHADOW:
                demoted.append(sample.action_type_id)
            await self._write_regression_audit(
                sample=sample,
                decision=decision,
                effective_mode=record.mode,
            )

        await self._write_run_audit(
            version=version,
            sample_count=len(samples),
            regressions=tuple(regressions),
            demoted=tuple(demoted),
            aborted_reason=None,
        )
        return BaselineRunReport(
            scenario_set_version=version,
            sample_count=len(samples),
            regressions=tuple(regressions),
            demoted_action_types=tuple(demoted),
        )

    # ------------------------------------------------------------------
    # audit helpers
    # ------------------------------------------------------------------

    async def _write_regression_audit(
        self,
        *,
        sample: MeasurementSample,
        decision: RegressionDecision,
        effective_mode: Mode,
    ) -> None:
        await self._audit_store.append_audit_entry(
            {
                "actor": "fdai.core.measurement.runners.baseline",
                "action_kind": "measurement.regression.demote",
                "mode": Mode.SHADOW.value,
                "action_type_id": sample.action_type_id,
                "scenario_set_version": sample.scenario_set_version,
                "outcome": decision.outcome.value,
                "reasons": list(decision.reasons),
                "effective_mode": effective_mode.value,
                "recorded_at": self._clock().isoformat(),
            }
        )

    async def _write_run_audit(
        self,
        *,
        version: str,
        sample_count: int,
        regressions: tuple[RegressionDecision, ...],
        demoted: tuple[str, ...],
        aborted_reason: str | None,
    ) -> None:
        outcome = (
            "aborted" if aborted_reason is not None else ("regression" if regressions else "pass")
        )
        await self._audit_store.append_audit_entry(
            {
                "actor": "fdai.core.measurement.runners.baseline",
                "action_kind": "measurement.regression.run",
                "mode": Mode.SHADOW.value,
                "scenario_set_version": version,
                "sample_count": sample_count,
                "outcome": outcome,
                "regression_count": len(regressions),
                "demoted_action_types": list(demoted),
                "aborted_reason": aborted_reason,
                "recorded_at": self._clock().isoformat(),
            }
        )


# ---------------------------------------------------------------------------
# PatternGrowthIntakeRunner - audit-driven pattern library growth.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatternGrowthReport:
    """Aggregate result for one :meth:`PatternGrowthIntakeRunner.run_once` call."""

    total_outcomes: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    ingested_signatures: tuple[str, ...] = field(default_factory=tuple)
    build_failures: int = 0
    intake_decisions: tuple[IntakeDecision, ...] = field(default_factory=tuple)
    deferred_count: int = 0
    expired_count: int = 0
    pending_budget_exhausted: bool = False


@dataclass(slots=True)
class _PendingDrainBudget:
    deadline: float
    exhausted: bool = False


@dataclass(frozen=True, slots=True)
class _GrowthRecordResult:
    decision: IntakeDecision
    disposition: Literal["rejected", "expired", "deferred", "build_failed", "ingested"]
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class DynamicLearningReport:
    total_outcomes: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    reasons: tuple[tuple[str, int], ...] = ()


class DynamicLearningRunner:
    """Apply response outcomes to registered challengers without promotion."""

    def __init__(
        self,
        *,
        outcome_source: ResponseOutcomeSource,
        registry: ChallengerUpdater,
        audit_store: StateStore,
        clock: Callable[[], datetime] | None = None,
        run_timeout_s: float = 300,
    ) -> None:
        self._outcome_source = outcome_source
        self._registry = registry
        self._audit_store = audit_store
        self._clock = clock or _default_clock
        if not math.isfinite(run_timeout_s) or run_timeout_s <= 0:
            raise ValueError("run_timeout_s MUST be finite and positive")
        self._run_timeout_s = run_timeout_s

    async def run_once(self) -> DynamicLearningReport:
        async with asyncio.timeout(self._run_timeout_s):
            return await self._run_once()

    async def _run_once(self) -> DynamicLearningReport:
        total = 0
        accepted = 0
        reasons: dict[str, int] = {}
        async for outcome in self._outcome_source.outcomes():
            total += 1
            result = await self._registry.update_from_outcome(outcome)
            if not result.accepted:
                await self._audit_store.append_audit_entry(
                    {
                        "actor": "Norns",
                        "producer_principal": "Norns",
                        "action_kind": "dynamic.learning.outcome_held",
                        "event_id": str(outcome.event_id),
                        "action_id": str(outcome.action_id),
                        "response_outcome_id": str(outcome.outcome_id),
                        "reason": result.reason,
                        "mode": Mode.SHADOW.value,
                        "execution_authority": False,
                        "recorded_at": self._clock().isoformat(),
                    }
                )
                retryable = result.reason in {
                    "challenger_not_registered",
                    "revision_conflict",
                    "untracked_challenger_requires_rebuild",
                } or (
                    outcome.schema_version == "1.1.0"
                    and result.reason
                    in {
                        "outcome_prediction_evidence_unavailable",
                        "model_generation_sources_unavailable",
                    }
                )
                if retryable:
                    raise RuntimeError(f"Dynamic learning retry required: {result.reason}")
            if result.accepted:
                accepted += 1
            reasons[result.reason] = reasons.get(result.reason, 0) + 1
        rejected = total - accepted
        ordered_reasons = tuple(sorted(reasons.items()))
        await self._audit_store.append_audit_entry(
            {
                "actor": "Norns",
                "producer_principal": "Norns",
                "action_kind": "dynamic.learning.run",
                "mode": Mode.SHADOW.value,
                "total_outcomes": total,
                "accepted_count": accepted,
                "rejected_count": rejected,
                "reasons": dict(ordered_reasons),
                "recorded_at": self._clock().isoformat(),
            }
        )
        return DynamicLearningReport(
            total_outcomes=total,
            accepted_count=accepted,
            rejected_count=rejected,
            reasons=ordered_reasons,
        )


class PatternGrowthIntakeRunner:
    """Audit-driven growth runner for the T1 pattern library.

    One invocation drains the :class:`OutcomeSource` once and returns.
    The Container Apps Job around it fires on a short cron (the "growth
    continuous" role in the ``measurement-runners`` module), so a busy
    system converges quickly while an idle one costs nothing.

    Shadow-first invariant
    ----------------------

    Growth NEVER auto-promotes. Every accepted candidate is normalized to
    ``historical_success_rate == 0.0`` and ``reuse_count == 0`` BEFORE it
    is handed to the :class:`PatternLibraryWriter`, so the T1 tier's
    ``min_success_rate`` floor filters it out of execution until a
    subsequent, measured promotion step lifts it. The
    :class:`PatternBuilder` may return whatever success rate it likes -
    the runner is the enforcement point.
    """

    __slots__ = (
        "_audit_store",
        "_builder",
        "_clock",
        "_outcome_source",
        "_pending",
        "_pending_max_age",
        "_item_timeout_s",
        "_run_timeout_s",
        "_writer",
    )

    def __init__(
        self,
        *,
        outcome_source: OutcomeSource,
        pattern_builder: PatternBuilder,
        writer: PatternLibraryWriter,
        audit_store: StateStore,
        clock: Callable[[], datetime] | None = None,
        pending_capacity: int = 1_000,
        pending_max_age: timedelta = timedelta(days=7),
        item_timeout_s: float = 60,
        run_timeout_s: float = 300,
    ) -> None:
        self._outcome_source = outcome_source
        self._builder = pattern_builder
        self._writer = writer
        self._audit_store = audit_store
        self._clock = clock or _default_clock
        if pending_max_age <= timedelta(0) or any(
            not math.isfinite(value) or value <= 0 for value in (item_timeout_s, run_timeout_s)
        ):
            raise ValueError("growth deadlines MUST be finite and positive")
        self._pending = PendingPatternGrowth(audit_store, capacity=pending_capacity)
        self._pending_max_age = pending_max_age
        self._item_timeout_s = item_timeout_s
        self._run_timeout_s = run_timeout_s

    async def run_once(self) -> PatternGrowthReport:
        """Drain the outcome source once and ingest accepted patterns."""
        async with asyncio.timeout(self._run_timeout_s):
            return await self._run_once()

    async def _records(
        self, budget: _PendingDrainBudget
    ) -> AsyncIterator[tuple[OutcomeRecord, bool]]:
        seen: set[str] = set()
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(max(0, budget.deadline - loop.time())):
                pending = await self._pending.records()
        except TimeoutError:
            budget.exhausted = True
            pending = ()
            _LOGGER.warning("pattern_growth_pending_read_deferred")
        owned = {record_key(record) for record in pending}
        for record in pending:
            if loop.time() >= budget.deadline:
                budget.exhausted = True
                break
            seen.add(record_key(record))
            yield record, True
        async for record in self._outcome_source.outcomes():
            key = record_key(record)
            if key not in seen and key not in owned:
                seen.add(key)
                yield record, False

    async def _run_once(self) -> PatternGrowthReport:
        loop = asyncio.get_running_loop()
        budget = _PendingDrainBudget(
            loop.time() + min(self._item_timeout_s, self._run_timeout_s / 2)
        )
        total = 0
        accepted = 0
        rejected = 0
        build_failures = 0
        deferred = 0
        expired = 0
        ingested: list[str] = []
        decisions: list[IntakeDecision] = []

        async for record, pending in self._records(budget):
            total += 1
            decision = evaluate_intake(record)
            decisions.append(decision)
            owned = pending
            try:
                item_budget = self._item_timeout_s
                if pending:
                    item_budget = min(item_budget, budget.deadline - loop.time())
                    if item_budget <= 0:
                        budget.exhausted = True
                        deferred += 1
                        continue
                async with asyncio.timeout(item_budget):
                    if decision.outcome is IntakeOutcome.ACCEPTED:
                        await self._write_intake_audit(
                            record=record,
                            decision=decision,
                            ingested=False,
                            reason="pattern_processing",
                            deferred=True,
                        )
                        owned = True
                    result = await self._process_record(record, pending, decision)
            except TimeoutError:
                if not owned:
                    raise RuntimeError(
                        "growth processing ownership is unconfirmed; source unacknowledged"
                    ) from None
                if pending and loop.time() >= budget.deadline:
                    budget.exhausted = True
                deferred += 1
                _LOGGER.warning(
                    "pattern_growth_owned_item_deferred",
                    extra={"record_digest": record_key(record)},
                )
                continue
            rejected += result.disposition == "rejected"
            expired += result.disposition == "expired"
            deferred += result.disposition == "deferred"
            build_failures += result.disposition == "build_failed"
            accepted += result.disposition == "ingested"
            if result.signature is not None:
                ingested.append(result.signature)

        await self._audit_store.append_audit_entry(
            {
                "actor": "fdai.core.measurement.runners.growth",
                "action_kind": "measurement.pattern_growth.run",
                "mode": Mode.SHADOW.value,
                "total_outcomes": total,
                "accepted_count": accepted,
                "rejected_count": rejected,
                "build_failures": build_failures,
                "deferred_count": deferred,
                "expired_count": expired,
                "pending_budget_exhausted": budget.exhausted,
                "recorded_at": self._clock().isoformat(),
            }
        )

        return PatternGrowthReport(
            total_outcomes=total,
            accepted_count=accepted,
            rejected_count=rejected,
            ingested_signatures=tuple(ingested),
            build_failures=build_failures,
            intake_decisions=tuple(decisions),
            deferred_count=deferred,
            expired_count=expired,
            pending_budget_exhausted=budget.exhausted,
        )

    async def _process_record(
        self, record: OutcomeRecord, pending: bool, decision: IntakeDecision
    ) -> _GrowthRecordResult:
        if decision.outcome is not IntakeOutcome.ACCEPTED:
            await self._write_intake_audit(
                record=record, decision=decision, ingested=False, reason=None
            )
            return _GrowthRecordResult(decision, "rejected")
        if pending and self._clock() >= record.observed_at + self._pending_max_age:
            await self._write_intake_audit(
                record=record, decision=decision, ingested=False, reason="evidence_deadline_expired"
            )
            return _GrowthRecordResult(decision, "expired")
        built = await self._builder.build(record)
        if isinstance(built, DeferredPatternBuild):
            overdue = self._clock() >= record.observed_at + self._pending_max_age
            await self._write_intake_audit(
                record=record,
                decision=decision,
                ingested=False,
                reason="evidence_deadline_expired" if overdue else built.reason,
                deferred=not overdue,
            )
            return _GrowthRecordResult(decision, "expired" if overdue else "deferred")
        if built is None:
            await self._write_intake_audit(
                record=record,
                decision=decision,
                ingested=False,
                reason="pattern_builder_returned_none",
            )
            return _GrowthRecordResult(decision, "build_failed")
        vector, candidate = built
        shadow_action = replace(candidate, success_rate=0.0, reuse_count=0)
        await self._writer.upsert_pattern(vector=vector, action=shadow_action)
        await self._write_intake_audit(
            record=record,
            decision=decision,
            ingested=True,
            reason=None,
            signature=shadow_action.signature,
        )
        return _GrowthRecordResult(decision, "ingested", shadow_action.signature)

    # ------------------------------------------------------------------
    # audit helper
    # ------------------------------------------------------------------

    async def _write_intake_audit(
        self,
        *,
        record: OutcomeRecord,
        decision: IntakeDecision,
        ingested: bool,
        reason: str | None,
        signature: str | None = None,
        deferred: bool = False,
    ) -> None:
        entry = {
            "actor": "fdai.core.measurement.runners.growth",
            "action_kind": "measurement.pattern_growth.intake",
            "mode": Mode.SHADOW.value,
            "action_id": record.action_id,
            "action_type_id": record.action_type_id,
            "intake_outcome": decision.outcome.value,
            "ingested": ingested,
            "signature": signature,
            "reason": reason,
            "deferred": deferred,
            "execution_authority": False,
            "promotion_authority": False,
            "recorded_at": self._clock().isoformat(),
        }
        if deferred:
            await self._pending.defer(record, entry)
        else:
            await self._pending.finish(record, entry)


__all__ = [
    "AutomatedBaselineRunner",
    "BaselineRunReport",
    "ChallengerUpdater",
    "DeferredPatternBuild",
    "DynamicLearningReport",
    "DynamicLearningRunner",
    "OutcomeSource",
    "PatternBuilder",
    "PatternGrowthIntakeRunner",
    "PatternGrowthReport",
    "ResponseOutcomeSource",
    "ScenarioReplayer",
]
