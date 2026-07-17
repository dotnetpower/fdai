"""DR and chaos scheduler facade with fail-closed safety preflight."""

from __future__ import annotations

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
    invoke_runner,
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

if TYPE_CHECKING:
    from fdai.shared.providers.dr_experiment import DrExperimentRunner


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
        return await self._invoke_runner(experiment=experiment, decision=decision, at=moment)

    async def _invoke_runner(
        self,
        *,
        experiment: DrExperiment,
        decision: SchedulerDecision,
        at: datetime,
    ) -> DrRunResult:
        runner = self._runner
        assert runner is not None  # noqa: S101 - guarded by run preflight
        return await invoke_runner(
            runner=runner,
            experiment=experiment,
            decision=decision,
            at=at,
        )


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
