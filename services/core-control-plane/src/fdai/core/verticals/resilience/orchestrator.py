"""DR and chaos scheduler facade with fail-closed safety preflight."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fdai.core.verticals.resilience.decision import decide_experiment
from fdai.core.verticals.resilience.evidence import (
    DrObjective,
    DrObjectiveReport,
    DrRunReport,
    summarize_runs,
)
from fdai.core.verticals.resilience.evidence import (
    percentile as _percentile,  # noqa: F401 - compatibility import
)
from fdai.core.verticals.resilience.execution import (
    check_runner,
    start_runner,
)
from fdai.core.verticals.resilience.execution import (
    safe_rollback as _safe_rollback,  # noqa: F401 - compatibility import
)
from fdai.core.verticals.resilience.execution import (
    truncate_error as _truncate_error,  # noqa: F401 - compatibility import
)
from fdai.core.verticals.resilience.models import (
    DrExperiment,
    DrRunResult,
    DrSchedulerConfig,
    ExecutionMode,
    FreezePeriod,
    MaintenanceWindow,
    RunOutcome,
    SchedulerDecision,
    SchedulerOutcome,
)
from fdai.shared.providers.dr_experiment import DrRunHandle, DrRunStatus

if TYPE_CHECKING:
    from fdai.shared.providers.dr_experiment import DrExperimentRunner


class _ActiveClaim:
    __slots__ = ("handle", "reason", "started_at")

    def __init__(
        self,
        *,
        handle: DrRunHandle | None = None,
        reason: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self.handle = handle
        self.reason = reason
        self.started_at = started_at


class DrScheduler:
    """Decide, validate safety invariants, and optionally invoke a runner."""

    def __init__(
        self,
        *,
        windows: Iterable[MaintenanceWindow],
        freezes: Iterable[FreezePeriod] = (),
        config: DrSchedulerConfig | None = None,
        runner: DrExperimentRunner | None = None,
    ) -> None:
        cfg = config or DrSchedulerConfig()
        if cfg.max_concurrent_experiments < 1:
            raise ValueError("max_concurrent_experiments MUST be >= 1")
        self._windows = tuple(windows)
        self._freezes = tuple(freezes)
        self._config = cfg
        self._runner = runner
        self._run_state_lock = asyncio.Lock()
        self._starting: set[str] = set()
        self._active_runs: dict[str, tuple[DrExperiment, DrRunHandle, datetime]] = {}
        self._polling: set[str] = set()

    def decide(
        self,
        *,
        experiment: DrExperiment,
        at: datetime | None = None,
        in_flight_experiments: int = 0,
    ) -> SchedulerDecision:
        """Return the ordered scheduler decision for an experiment."""
        return decide_experiment(
            experiment=experiment,
            at=at or datetime.now(tz=UTC),
            in_flight_experiments=in_flight_experiments,
            windows=self._windows,
            freezes=self._freezes,
            config=self._config,
        )

    async def run(
        self,
        *,
        experiment: DrExperiment,
        mode: ExecutionMode,
        at: datetime | None = None,
        in_flight_experiments: int = 0,
    ) -> DrRunResult:
        """Decide, enforce safety preflight, then dispatch when allowed."""
        moment = at or datetime.now(tz=UTC)
        if mode is ExecutionMode.ENFORCE:
            claim = await self._claim_active(experiment)
            if claim.handle is not None:
                assert claim.started_at is not None  # noqa: S101 - handle and start are paired
                return await self._poll_active(
                    experiment=experiment,
                    handle=claim.handle,
                    at=moment,
                    started_at=claim.started_at,
                )
            if claim.reason is not None:
                return self._active_conflict_result(
                    experiment=experiment,
                    at=moment,
                    reason=claim.reason,
                )

        decision = self.decide(
            experiment=experiment,
            at=moment,
            in_flight_experiments=in_flight_experiments,
        )
        if decision.outcome is not SchedulerOutcome.ALLOWED:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.NOT_ALLOWED,
                decision=decision,
                at=moment,
            )
        if experiment.is_production_target:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.ISOLATION_VIOLATION,
                decision=decision,
                at=moment,
                reasons=("isolation:target_is_production",),
            )
        if not experiment.has_rollback_path:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.MISSING_ROLLBACK_PATH,
                decision=decision,
                at=moment,
                reasons=("rollback:not_declared",),
            )
        if not experiment.stop_conditions:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.MISSING_STOP_CONDITION,
                decision=decision,
                at=moment,
                reasons=("stop_condition:not_declared",),
            )
        if (
            not math.isfinite(experiment.max_duration_seconds)
            or experiment.max_duration_seconds <= 0
        ):
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.INVALID_TIME_BOX,
                decision=decision,
                at=moment,
                reasons=("stop_condition:invalid_time_box",),
            )
        if mode is ExecutionMode.SHADOW:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.SHADOW_LOGGED,
                decision=decision,
                at=moment,
                reasons=("mode:shadow",),
            )
        if experiment.provider_ref is None:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.MISSING_PROVIDER_REF,
                decision=decision,
                at=moment,
                reasons=("provider_ref:required_for_enforce",),
            )
        if self._runner is None:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.RUNNER_NOT_CONFIGURED,
                decision=decision,
                at=moment,
                reasons=("runner:not_injected",),
            )
        reserved = await self._reserve_start(
            experiment=experiment,
            at=moment,
            external_in_flight=in_flight_experiments,
        )
        if reserved.outcome is not SchedulerOutcome.ALLOWED:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.NOT_ALLOWED,
                decision=reserved,
                at=moment,
            )
        return await self._start_and_poll(
            experiment=experiment,
            decision=reserved,
            at=moment,
        )

    async def _claim_active(self, experiment: DrExperiment) -> _ActiveClaim:
        async with self._run_state_lock:
            active = self._active_runs.get(experiment.experiment_id)
            if active is None:
                if experiment.experiment_id in self._starting:
                    return _ActiveClaim(reason="experiment_start_in_progress")
                return _ActiveClaim()
            tracked_experiment, handle, started_at = active
            if tracked_experiment != experiment:
                return _ActiveClaim(reason="active_experiment_definition_mismatch")
            if experiment.experiment_id in self._polling:
                return _ActiveClaim(reason="experiment_poll_in_progress")
            self._polling.add(experiment.experiment_id)
            return _ActiveClaim(handle=handle, started_at=started_at)

    async def _reserve_start(
        self,
        *,
        experiment: DrExperiment,
        at: datetime,
        external_in_flight: int,
    ) -> SchedulerDecision:
        async with self._run_state_lock:
            if (
                experiment.experiment_id in self._starting
                or experiment.experiment_id in self._active_runs
            ):
                return SchedulerDecision(
                    experiment_id=experiment.experiment_id,
                    outcome=SchedulerOutcome.CONCURRENCY_CAP,
                    reasons=("experiment_already_active",),
                    at=at,
                )
            effective_in_flight = external_in_flight + len(self._starting) + len(self._active_runs)
            decision = self.decide(
                experiment=experiment,
                at=at,
                in_flight_experiments=effective_in_flight,
            )
            if decision.outcome is SchedulerOutcome.ALLOWED:
                self._starting.add(experiment.experiment_id)
            return decision

    async def _start_and_poll(
        self,
        *,
        experiment: DrExperiment,
        decision: SchedulerDecision,
        at: datetime,
    ) -> DrRunResult:
        runner = self._runner
        assert runner is not None  # noqa: S101 - guarded by run preflight
        try:
            start_task = asyncio.create_task(
                start_runner(
                    runner=runner,
                    experiment=experiment,
                    decision=decision,
                    at=at,
                )
            )
            try:
                started = await asyncio.shield(start_task)
            except asyncio.CancelledError:
                started = await start_task
                if started.handle is not None:
                    await self._register_active(
                        experiment=experiment,
                        handle=started.handle,
                        started_at=at,
                        claim_poll=False,
                    )
                else:
                    await self._release_start(experiment.experiment_id)
                raise
            if started.handle is None:
                await self._release_start(experiment.experiment_id)
                return started
            await self._register_active(
                experiment=experiment,
                handle=started.handle,
                started_at=at,
                claim_poll=True,
            )
            return await self._poll_active(
                experiment=experiment,
                handle=started.handle,
                at=at,
                started_at=at,
            )
        except BaseException:
            await self._release_start(experiment.experiment_id)
            raise

    async def _register_active(
        self,
        *,
        experiment: DrExperiment,
        handle: DrRunHandle,
        started_at: datetime,
        claim_poll: bool,
    ) -> None:
        async with self._run_state_lock:
            self._starting.discard(experiment.experiment_id)
            self._active_runs[experiment.experiment_id] = (experiment, handle, started_at)
            if claim_poll:
                self._polling.add(experiment.experiment_id)

    async def _poll_active(
        self,
        *,
        experiment: DrExperiment,
        handle: DrRunHandle,
        at: datetime,
        started_at: datetime,
    ) -> DrRunResult:
        runner = self._runner
        assert runner is not None  # noqa: S101 - active handles require a runner
        decision = SchedulerDecision(
            experiment_id=experiment.experiment_id,
            outcome=SchedulerOutcome.ALLOWED,
            reasons=("active_experiment_resume",),
            at=at,
        )
        elapsed = (at - started_at).total_seconds()
        if elapsed < 0:
            await self._finish_poll(experiment.experiment_id, keep_active=True)
            return self._active_conflict_result(
                experiment=experiment,
                at=at,
                reason="experiment_clock_regressed",
            )
        if elapsed >= experiment.max_duration_seconds:
            rollback_error = await _safe_rollback(runner, handle)
            reasons: tuple[str, ...] = ("stop_condition:time_box_exceeded",)
            if rollback_error is not None:
                reasons = (*reasons, "rollback:error")
            result = DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.ROLLED_BACK,
                decision=decision,
                handle=handle,
                status=DrRunStatus.STOPPED,
                at=at,
                reasons=reasons,
            )
            await self._finish_poll(
                experiment.experiment_id,
                keep_active=rollback_error is not None,
            )
            return result
        try:
            result = await check_runner(
                runner=runner,
                handle=handle,
                decision=decision,
                at=at,
            )
        except BaseException:
            await self._finish_poll(experiment.experiment_id, keep_active=True)
            raise
        keep_active = (
            result.status is DrRunStatus.RUNNING and result.outcome is RunOutcome.EXECUTED
        ) or "rollback:error" in result.reasons
        await self._finish_poll(experiment.experiment_id, keep_active=keep_active)
        return result

    async def _release_start(self, experiment_id: str) -> None:
        async with self._run_state_lock:
            self._starting.discard(experiment_id)

    async def _finish_poll(self, experiment_id: str, *, keep_active: bool) -> None:
        async with self._run_state_lock:
            self._polling.discard(experiment_id)
            if not keep_active:
                self._active_runs.pop(experiment_id, None)

    def _active_conflict_result(
        self,
        *,
        experiment: DrExperiment,
        at: datetime,
        reason: str,
    ) -> DrRunResult:
        decision = SchedulerDecision(
            experiment_id=experiment.experiment_id,
            outcome=SchedulerOutcome.CONCURRENCY_CAP,
            reasons=(reason,),
            at=at,
        )
        return DrRunResult(
            experiment_id=experiment.experiment_id,
            outcome=RunOutcome.NOT_ALLOWED,
            decision=decision,
            at=at,
            reasons=(reason,),
        )

    async def active_experiment_ids(self) -> tuple[str, ...]:
        """Return stable in-process active ids for diagnostics and tests."""
        async with self._run_state_lock:
            return tuple(sorted((*self._starting, *self._active_runs)))


__all__ = [
    "DrExperiment",
    "DrObjective",
    "DrObjectiveReport",
    "DrRunReport",
    "DrRunResult",
    "DrScheduler",
    "DrSchedulerConfig",
    "ExecutionMode",
    "FreezePeriod",
    "MaintenanceWindow",
    "RunOutcome",
    "SchedulerDecision",
    "SchedulerOutcome",
    "summarize_runs",
]
