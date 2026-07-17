"""Pure resilience scheduling decisions."""

from __future__ import annotations

from datetime import datetime

from fdai.core.verticals.resilience.models import (
    DrExperiment,
    DrSchedulerConfig,
    FreezePeriod,
    MaintenanceWindow,
    SchedulerDecision,
    SchedulerOutcome,
)


def decide_experiment(
    *,
    experiment: DrExperiment,
    at: datetime,
    in_flight_experiments: int,
    windows: tuple[MaintenanceWindow, ...],
    freezes: tuple[FreezePeriod, ...],
    config: DrSchedulerConfig,
) -> SchedulerDecision:
    """Apply freeze, window, opt-out, and concurrency checks in order."""
    for freeze in freezes:
        if freeze.contains(at):
            return SchedulerDecision(
                experiment_id=experiment.experiment_id,
                outcome=SchedulerOutcome.FROZEN,
                reasons=(f"freeze:{freeze.name}",),
                at=at,
            )

    active = [window for window in windows if window.contains(at)]
    if not active:
        return SchedulerDecision(
            experiment_id=experiment.experiment_id,
            outcome=SchedulerOutcome.OUTSIDE_WINDOW,
            reasons=("no_active_window",),
            at=at,
        )

    if config.opt_out_tag in experiment.target_resource_tags:
        return SchedulerDecision(
            experiment_id=experiment.experiment_id,
            outcome=SchedulerOutcome.OPT_OUT,
            reasons=(f"opt_out_tag:{config.opt_out_tag}",),
            at=at,
        )

    if in_flight_experiments >= config.max_concurrent_experiments:
        return SchedulerDecision(
            experiment_id=experiment.experiment_id,
            outcome=SchedulerOutcome.CONCURRENCY_CAP,
            reasons=(
                f"in_flight={in_flight_experiments}>=cap={config.max_concurrent_experiments}",
            ),
            at=at,
        )

    return SchedulerDecision(
        experiment_id=experiment.experiment_id,
        outcome=SchedulerOutcome.ALLOWED,
        reasons=(f"window:{active[0].name}",),
        at=at,
    )
