"""End-to-end tests for :meth:`DrScheduler.run` — safety invariants + runner dispatch.

Covers the phase-3 DR / Chaos contract in
[`docs/roadmap/phases/phase-3-integrated-loop.md § DR / Chaos`]:

- **Stop-condition invariant** — enforce refuses without at least one declared
  stop-condition.
- **Blast-radius / concurrency invariant** — the ``max_concurrent_experiments``
  cap short-circuits ``run`` with ``NOT_ALLOWED`` when the in-flight count
  is at or above the cap.
- **Rollback invariant** — enforce refuses without a declared rollback path;
  when a run fails (either at ``check`` or with an explicit ``FAILED`` /
  ``STOPPED`` status) the scheduler MUST invoke the runner's rollback.
- **Isolation invariant** — a production target is refused in enforce mode.

Every test drives the scheduler with a :class:`FakeDrExperimentRunner` so
we can assert on the exact sequence of ``start`` / ``check`` / ``rollback``
calls the runner Protocol receives. Shadow-mode tests assert on ZERO
runner calls — the "shadow mode never mutates" property from the
coding conventions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aiopspilot.core.verticals.resilience import (
    DrExperiment,
    DrScheduler,
    DrSchedulerConfig,
    ExecutionMode,
    MaintenanceWindow,
    RunOutcome,
    SchedulerOutcome,
)
from aiopspilot.shared.providers.dr_experiment import DrRunStatus
from aiopspilot.shared.providers.testing.dr_experiment import (
    FakeDrExperimentRunner,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


_WINDOW_START = "2026-07-05T02:00:00"
_WINDOW_END = "2026-07-05T04:00:00"
_INSIDE = _at("2026-07-05T03:00:00")
_OUTSIDE = _at("2026-07-05T05:00:00")


def _window() -> MaintenanceWindow:
    return MaintenanceWindow(
        name="sun-2am",
        start=_at(_WINDOW_START),
        end=_at(_WINDOW_END),
    )


def _experiment(
    *,
    experiment_id: str = "exp-1",
    is_production_target: bool = False,
    has_rollback_path: bool = True,
    stop_conditions: tuple[str, ...] = ("health-probe-failure",),
    provider_ref: str | None = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
        "rg-example/providers/Microsoft.Chaos/experiments/exp-1"
    ),
    tags: frozenset[str] = frozenset(),
) -> DrExperiment:
    return DrExperiment(
        experiment_id=experiment_id,
        target_resource_ref="res-1",
        target_resource_tags=tags,
        provider_ref=provider_ref,
        is_production_target=is_production_target,
        has_rollback_path=has_rollback_path,
        stop_conditions=stop_conditions,
    )


def _scheduler(
    *,
    runner: FakeDrExperimentRunner | None = None,
    max_concurrent: int = 1,
) -> DrScheduler:
    return DrScheduler(
        windows=[_window()],
        config=DrSchedulerConfig(max_concurrent_experiments=max_concurrent),
        runner=runner,
    )


# ---------------------------------------------------------------------------
# Shadow mode — never invokes the runner
# ---------------------------------------------------------------------------


async def test_shadow_mode_never_invokes_runner_on_allowed_decision() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.SHADOW,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.SHADOW_LOGGED
    assert result.decision.outcome is SchedulerOutcome.ALLOWED
    assert runner.started == []
    assert runner.checked == []
    assert runner.rolled_back == []


async def test_shadow_mode_still_reports_scheduler_rejection() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.SHADOW,
        at=_OUTSIDE,  # outside window → NOT_ALLOWED
    )

    assert result.outcome is RunOutcome.NOT_ALLOWED
    assert result.decision.outcome is SchedulerOutcome.OUTSIDE_WINDOW
    assert runner.started == []


async def test_shadow_mode_works_without_runner_configured() -> None:
    # A fork MAY run a scheduler in shadow-only mode without wiring a
    # runner at all; the decision + preflight still fire and the
    # outcome is ``SHADOW_LOGGED`` on a green path.
    scheduler = _scheduler(runner=None)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.SHADOW,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.SHADOW_LOGGED


# ---------------------------------------------------------------------------
# Enforce mode — happy path
# ---------------------------------------------------------------------------


async def test_enforce_mode_invokes_start_then_check_on_success() -> None:
    runner = FakeDrExperimentRunner(status_sequence=(DrRunStatus.SUCCEEDED,))
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.EXECUTED
    assert result.status is DrRunStatus.SUCCEEDED
    assert result.handle is not None
    assert result.handle.experiment_id == "exp-1"
    # Exactly one start + one check; no rollback on success.
    assert len(runner.started) == 1
    assert len(runner.checked) == 1
    assert runner.rolled_back == []


# ---------------------------------------------------------------------------
# Enforce mode — failure paths trigger rollback
# ---------------------------------------------------------------------------


async def test_enforce_mode_rolls_back_on_failed_status() -> None:
    runner = FakeDrExperimentRunner(status_sequence=(DrRunStatus.FAILED,))
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.ROLLED_BACK
    assert result.status is DrRunStatus.FAILED
    assert len(runner.started) == 1
    assert len(runner.checked) == 1
    assert len(runner.rolled_back) == 1
    assert runner.rolled_back[0].experiment_id == "exp-1"


async def test_enforce_mode_rolls_back_on_stopped_status() -> None:
    runner = FakeDrExperimentRunner(status_sequence=(DrRunStatus.STOPPED,))
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.ROLLED_BACK
    assert result.status is DrRunStatus.STOPPED
    assert len(runner.rolled_back) == 1


async def test_enforce_mode_no_rollback_when_still_running() -> None:
    # ``RUNNING`` at the one-shot check is not a rollback trigger — the
    # caller is expected to schedule another ``run`` later. This shields
    # long LROs from being killed after their first partial poll.
    runner = FakeDrExperimentRunner(status_sequence=(DrRunStatus.RUNNING,))
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.EXECUTED
    assert result.status is DrRunStatus.RUNNING
    assert runner.rolled_back == []


async def test_enforce_mode_records_failure_on_start_error() -> None:
    runner = FakeDrExperimentRunner(start_error=RuntimeError("simulated auth failure"))
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    # start failed → no handle → we cannot rollback → outcome is FAILED,
    # not ROLLED_BACK. The audit reason should mention start_failed.
    assert result.outcome is RunOutcome.FAILED
    assert result.handle is None
    assert result.error is not None
    assert "simulated auth failure" in result.error
    assert "runner:start_failed" in result.reasons
    assert runner.rolled_back == []


async def test_enforce_mode_rolls_back_on_check_error() -> None:
    runner = FakeDrExperimentRunner(check_error=RuntimeError("check-transport-blip"))
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    # check failed after a successful start → rollback the run.
    assert result.outcome is RunOutcome.ROLLED_BACK
    assert result.handle is not None
    assert result.error is not None
    assert "check-transport-blip" in result.error
    assert len(runner.rolled_back) == 1


async def test_enforce_mode_records_rollback_error_reason() -> None:
    # If rollback ITSELF fails, we still record the original failure as
    # the primary outcome; the rollback error appears as a reason tag.
    runner = FakeDrExperimentRunner(
        status_sequence=(DrRunStatus.FAILED,),
        rollback_error=RuntimeError("rollback-substrate-down"),
    )
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.ROLLED_BACK
    assert "rollback:error" in result.reasons
    # The rollback path was still attempted even though it raised.
    assert runner.rolled_back == []


async def test_enforce_mode_records_rollback_error_when_check_raises() -> None:
    runner = FakeDrExperimentRunner(
        check_error=RuntimeError("check-blip"),
        rollback_error=RuntimeError("rollback-boom"),
    )
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.ROLLED_BACK
    assert "rollback:error" in result.reasons


# ---------------------------------------------------------------------------
# Safety invariants — enforced BEFORE the runner is invoked
# ---------------------------------------------------------------------------


async def test_isolation_invariant_blocks_production_target() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(is_production_target=True),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.ISOLATION_VIOLATION
    # Runner MUST NOT be touched — the invariant is enforced BEFORE dispatch.
    assert runner.started == []


async def test_missing_rollback_path_blocks_enforce() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(has_rollback_path=False),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.MISSING_ROLLBACK_PATH
    assert runner.started == []


async def test_missing_stop_condition_blocks_enforce() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(stop_conditions=()),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.MISSING_STOP_CONDITION
    assert runner.started == []


async def test_missing_provider_ref_blocks_enforce() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(provider_ref=None),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.MISSING_PROVIDER_REF
    assert runner.started == []


async def test_enforce_without_runner_configured_short_circuits() -> None:
    scheduler = _scheduler(runner=None)  # no runner injected

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
    )

    assert result.outcome is RunOutcome.RUNNER_NOT_CONFIGURED


# ---------------------------------------------------------------------------
# Blast-radius invariant — concurrency cap short-circuits enforce
# ---------------------------------------------------------------------------


async def test_concurrent_cap_blocks_run_before_touching_runner() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner, max_concurrent=1)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
        in_flight_experiments=1,  # already at cap
    )

    assert result.outcome is RunOutcome.NOT_ALLOWED
    assert result.decision.outcome is SchedulerOutcome.CONCURRENCY_CAP
    assert runner.started == []


async def test_concurrent_cap_allows_run_when_slot_free() -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner, max_concurrent=2)

    result = await scheduler.run(
        experiment=_experiment(),
        mode=ExecutionMode.ENFORCE,
        at=_INSIDE,
        in_flight_experiments=1,  # 1/2 slots used
    )

    assert result.outcome is RunOutcome.EXECUTED
    assert len(runner.started) == 1


# ---------------------------------------------------------------------------
# Window / freeze / opt-out — routing to NOT_ALLOWED without runner touch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "at,tags,scheduler_outcome",
    [
        (_OUTSIDE, frozenset(), SchedulerOutcome.OUTSIDE_WINDOW),
        (_INSIDE, frozenset({"chaos:opt-out"}), SchedulerOutcome.OPT_OUT),
    ],
)
async def test_decision_short_circuits_before_invariants(
    at: datetime,
    tags: frozenset[str],
    scheduler_outcome: SchedulerOutcome,
) -> None:
    runner = FakeDrExperimentRunner()
    scheduler = _scheduler(runner=runner)

    result = await scheduler.run(
        experiment=_experiment(tags=tags, is_production_target=True),
        mode=ExecutionMode.ENFORCE,
        at=at,
    )

    # The decision blocked the run before the isolation invariant even
    # got a chance to fire — the outcome is NOT_ALLOWED, not
    # ISOLATION_VIOLATION.
    assert result.outcome is RunOutcome.NOT_ALLOWED
    assert result.decision.outcome is scheduler_outcome
    assert runner.started == []


async def test_fake_rejects_empty_status_sequence() -> None:
    with pytest.raises(ValueError, match="status_sequence"):
        FakeDrExperimentRunner(status_sequence=())


async def test_fake_repeats_last_status_after_sequence_exhausted() -> None:
    # Two checks on the same run — first returns RUNNING, second (and
    # every one after) returns SUCCEEDED. Guards against a fake that
    # would raise IndexError once the sequence is exhausted.
    runner = FakeDrExperimentRunner(status_sequence=(DrRunStatus.RUNNING, DrRunStatus.SUCCEEDED))
    handle = await runner.start(_experiment())
    assert await runner.check(handle) is DrRunStatus.RUNNING
    assert await runner.check(handle) is DrRunStatus.SUCCEEDED
    # A third check keeps returning the last value.
    assert await runner.check(handle) is DrRunStatus.SUCCEEDED
