"""DR scheduler + RPO/RTO reporting invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.verticals.resilience import (
    DrExperiment,
    DrObjective,
    DrObjectiveReport,
    DrRunReport,
    DrScheduler,
    DrSchedulerConfig,
    FreezePeriod,
    MaintenanceWindow,
    SchedulerOutcome,
    summarize_runs,
)


def _window(name: str, start: str, end: str) -> MaintenanceWindow:
    return MaintenanceWindow(
        name=name,
        start=datetime.fromisoformat(start).replace(tzinfo=UTC),
        end=datetime.fromisoformat(end).replace(tzinfo=UTC),
    )


def _freeze(name: str, start: str, end: str) -> FreezePeriod:
    return FreezePeriod(
        name=name,
        start=datetime.fromisoformat(start).replace(tzinfo=UTC),
        end=datetime.fromisoformat(end).replace(tzinfo=UTC),
    )


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


def _experiment(*, tags: frozenset[str] = frozenset()) -> DrExperiment:
    return DrExperiment(
        experiment_id="exp-1", target_resource_ref="res-1", target_resource_tags=tags
    )


# ---------------------------------------------------------------------------
# Scheduler decisions
# ---------------------------------------------------------------------------


def test_scheduler_rejects_zero_concurrency_cap() -> None:
    with pytest.raises(ValueError, match="max_concurrent_experiments"):
        DrScheduler(
            windows=[],
            config=DrSchedulerConfig(max_concurrent_experiments=0),
        )


def test_outside_maintenance_window_is_blocked() -> None:
    scheduler = DrScheduler(
        windows=[_window("sun-2am", "2026-07-05T02:00:00", "2026-07-05T04:00:00")]
    )
    decision = scheduler.decide(experiment=_experiment(), at=_at("2026-07-05T05:00:00"))
    assert decision.outcome is SchedulerOutcome.OUTSIDE_WINDOW


def test_freeze_period_overrides_active_window() -> None:
    scheduler = DrScheduler(
        windows=[_window("sun-2am", "2026-07-05T02:00:00", "2026-07-05T04:00:00")],
        freezes=[_freeze("holiday", "2026-07-05T00:00:00", "2026-07-05T23:59:00")],
    )
    decision = scheduler.decide(experiment=_experiment(), at=_at("2026-07-05T03:00:00"))
    assert decision.outcome is SchedulerOutcome.FROZEN
    assert any("freeze:holiday" in r for r in decision.reasons)


def test_opt_out_tag_blocks_experiment() -> None:
    scheduler = DrScheduler(
        windows=[_window("sun-2am", "2026-07-05T02:00:00", "2026-07-05T04:00:00")]
    )
    decision = scheduler.decide(
        experiment=_experiment(tags=frozenset({"chaos:opt-out"})),
        at=_at("2026-07-05T03:00:00"),
    )
    assert decision.outcome is SchedulerOutcome.OPT_OUT


def test_concurrency_cap_blocks_when_reached() -> None:
    scheduler = DrScheduler(
        windows=[_window("sun-2am", "2026-07-05T02:00:00", "2026-07-05T04:00:00")],
        config=DrSchedulerConfig(max_concurrent_experiments=1),
    )
    decision = scheduler.decide(
        experiment=_experiment(),
        at=_at("2026-07-05T03:00:00"),
        in_flight_experiments=1,
    )
    assert decision.outcome is SchedulerOutcome.CONCURRENCY_CAP


def test_negative_in_flight_count_is_rejected() -> None:
    scheduler = DrScheduler(
        windows=[_window("sun-2am", "2026-07-05T02:00:00", "2026-07-05T04:00:00")]
    )
    with pytest.raises(ValueError, match="in_flight_experiments"):
        scheduler.decide(
            experiment=_experiment(),
            at=_at("2026-07-05T03:00:00"),
            in_flight_experiments=-1,
        )


def test_experiment_allowed_when_all_guards_pass() -> None:
    scheduler = DrScheduler(
        windows=[_window("sun-2am", "2026-07-05T02:00:00", "2026-07-05T04:00:00")]
    )
    decision = scheduler.decide(experiment=_experiment(), at=_at("2026-07-05T03:00:00"))
    assert decision.outcome is SchedulerOutcome.ALLOWED
    assert any("window:sun-2am" in r for r in decision.reasons)


def test_no_windows_configured_is_always_outside() -> None:
    scheduler = DrScheduler(windows=[])
    decision = scheduler.decide(experiment=_experiment(), at=_at("2026-07-05T03:00:00"))
    assert decision.outcome is SchedulerOutcome.OUTSIDE_WINDOW


# ---------------------------------------------------------------------------
# RPO/RTO summarize
# ---------------------------------------------------------------------------


def test_summarize_empty_runs_returns_sentinel_medians() -> None:
    objective = DrObjective(max_rpo_seconds=60, max_rto_seconds=1800)
    report = summarize_runs(runs=[], objective=objective)
    assert isinstance(report, DrObjectiveReport)
    assert report.run_count == 0
    assert report.rpo_median_seconds == -1.0
    assert report.rto_median_seconds == -1.0
    assert report.rpo_objective_met is False
    assert report.rto_objective_met is False


def test_summarize_reports_median_and_p90() -> None:
    now = _at("2026-07-05T04:00:00")
    runs = [
        DrRunReport(
            experiment_id=f"e-{i}",
            completed_at=now,
            rpo_seconds=float(i),
            rto_seconds=float(i * 60),
        )
        for i in range(1, 11)
    ]
    report = summarize_runs(
        runs=runs, objective=DrObjective(max_rpo_seconds=100, max_rto_seconds=1000)
    )
    assert report.run_count == 10
    assert report.rpo_median_seconds == 5.5
    assert report.rpo_p90_seconds == 9.0
    assert report.rto_p90_seconds == 540.0
    # None of the runs breach the generous 100s / 1000s objectives.
    assert report.breach_count == 0
    assert report.rpo_objective_met
    assert report.rto_objective_met


def test_summarize_counts_breaches_against_objective() -> None:
    now = _at("2026-07-05T04:00:00")
    runs = [
        DrRunReport(
            experiment_id="e-good",
            completed_at=now,
            rpo_seconds=30,
            rto_seconds=200,
        ),
        DrRunReport(
            experiment_id="e-rpo-breach",
            completed_at=now,
            rpo_seconds=120,  # breaches 60s
            rto_seconds=200,
        ),
        DrRunReport(
            experiment_id="e-rto-breach",
            completed_at=now,
            rpo_seconds=30,
            rto_seconds=2000,  # breaches 1000s
        ),
    ]
    report = summarize_runs(
        runs=runs, objective=DrObjective(max_rpo_seconds=60, max_rto_seconds=1000)
    )
    assert report.breach_count == 2


def test_summarize_aggregates_integrity_and_smoke_failures() -> None:
    now = _at("2026-07-05T04:00:00")
    runs = [
        DrRunReport(
            experiment_id="e-a",
            completed_at=now,
            rpo_seconds=1,
            rto_seconds=1,
            integrity_mismatches=2,
            smoke_pass=False,
        ),
        DrRunReport(
            experiment_id="e-b",
            completed_at=now,
            rpo_seconds=1,
            rto_seconds=1,
            integrity_mismatches=1,
            smoke_pass=True,
        ),
    ]
    report = summarize_runs(
        runs=runs, objective=DrObjective(max_rpo_seconds=60, max_rto_seconds=60)
    )
    assert report.integrity_mismatches_total == 3
    assert report.smoke_failures == 1
